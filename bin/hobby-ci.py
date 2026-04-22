#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-digitalocean>=1.17.0",
#     "requests>=2.28.0",
#     "paramiko>=3.0.0",
# ]
# ///
# ruff: noqa: T201 allow print statements

import os
import sys
import time
import shlex
import datetime
from dataclasses import dataclass

import urllib3
import requests
import digitalocean  # type: ignore

DOMAIN = os.getenv("HOBBY_DOMAIN", "posthog.cc")
FALLBACK_SIZE = "g-8vcpu-32gb"


class HobbyTester:
    def __init__(
        self,
        token=None,
        name=None,
        region="sfo3",
        image="ubuntu-22-04-x64",
        size="s-8vcpu-16gb",
        branch=None,
        hostname=None,
        domain=DOMAIN,
        droplet_id=None,
        droplet=None,
        record_id=None,
        record=None,
        sha=None,
        pr_number=None,
        ssh_private_key=None,
    ):
        if not token:
            token = os.getenv("DIGITALOCEAN_TOKEN")
        self.token = token
        self.branch = branch
        self.sha = sha
        self.pr_number = pr_number

        self.name = name

        if not hostname:
            hostname = f"{name}.{DOMAIN}"
        self.hostname = hostname

        self.region = region
        self.image = image
        self.size = size

        self.domain = domain
        self.droplet = droplet
        if droplet_id:
            self.droplet = digitalocean.Droplet(token=self.token, id=droplet_id)
            self.droplet.load()

        self.record = record
        if record_id:
            self.record = digitalocean.Record(token=self.token, id=record_id)

        # SSH private key from secrets (DIGITALOCEAN_SSH_PRIVATE_KEY)
        # This key matches posthog-ci-cd registered in DigitalOcean
        self.ssh_private_key = ssh_private_key or os.environ.get("DIGITALOCEAN_SSH_PRIVATE_KEY")

        # Only build user_data if we don't already have a droplet (i.e., creating a new one)
        if not droplet_id:
            self.user_data = self._build_user_data()
        else:
            self.user_data = None

    def _get_wait_for_image_script(self):
        """Return bash script to wait for docker image on DockerHub with fallback to build.
        Returns a single-line bash command suitable for YAML runcmd.
        """
        # Use semicolons to chain commands on a single line
        # Simplified: just check if the commit SHA appears in the response (avoiding complex quote escaping)
        return (
            "WAIT_TIMEOUT=1200; "
            "WAIT_INTERVAL=30; "
            "END_TIME=$(($(date +%s) + WAIT_TIMEOUT)); "
            "IMAGE_FOUND=false; "
            "while [ $(date +%s) -lt $END_TIME ]; do "
            "  MINS_LEFT=$(( (END_TIME - $(date +%s)) / 60 )); "
            '  if curl -s "https://hub.docker.com/v2/repositories/posthog/posthog/tags/$CURRENT_COMMIT" | grep -q "$CURRENT_COMMIT"; then '
            '    echo "$LOG_PREFIX Docker image found on DockerHub"; '
            "    IMAGE_FOUND=true; "
            "    break; "
            "  fi; "
            '  echo "$LOG_PREFIX Image not yet available, checking again in 30s... ($MINS_LEFT mins remaining)"; '
            "  sleep $WAIT_INTERVAL; "
            "done; "
            'if [ "$IMAGE_FOUND" = false ]; then '
            '  echo "$LOG_PREFIX Image not found after 20 mins, building locally..."; '
            "  cd posthog; "
            "  docker build -t posthog/posthog:$CURRENT_COMMIT .; "
            "  cd ..; "
            "fi"
        )

    def _get_node_image_fallback_script(self):
        """Return bash script to resolve the posthog-node image tag.

        ci-nodejs-container.yml tags images as pr-<number> for PRs.
        Checks DockerHub for that tag; if found, exports POSTHOG_NODE_TAG
        so the hobby-installer writes it to .env and docker-compose uses
        the branch image. Otherwise falls back to 'latest'.
        """
        if self.pr_number and self.pr_number != "unknown":
            tag = f"pr-{self.pr_number}"
        else:
            tag = "$CURRENT_COMMIT"
        return (
            "if curl -sf "
            f"https://hub.docker.com/v2/repositories/posthog/posthog-node/tags/{tag} "
            "> /dev/null 2>&1; then "
            f"echo posthog-node image found on DockerHub with tag {tag}; "
            f"export POSTHOG_NODE_TAG={tag}; "
            "else "
            "echo posthog-node image not found, using latest; "
            "export POSTHOG_NODE_TAG=latest; "
            "fi"
        )

    def _get_installer_commands(self):
        """Return cloud-init commands to obtain the hobby-installer binary.

        If INSTALLER_CHANGED is set (Go code was modified in this PR), build
        from the checked-out source so the e2e test validates the new code.
        Otherwise download the latest release to keep provisioning fast.
        """
        installer_changed = os.environ.get("INSTALLER_CHANGED", "false").lower() == "true"

        if installer_changed:
            return [
                'echo "$LOG_PREFIX Building hobby installer from source (installer code changed)..."',
                "curl -fsSL https://go.dev/dl/go1.24.0.linux-$(dpkg --print-architecture).tar.gz | tar -C /usr/local -xzf -",
                "export PATH=$PATH:/usr/local/go/bin",
                "export GOPATH=/tmp/go",
                "export GOCACHE=/tmp/go-cache",
                "cd posthog/bin/hobby-installer && go build -o /tmp/hobby-installer . && cd ../../..",
                "cp /tmp/hobby-installer hobby-installer",
                "chmod +x hobby-installer",
            ]

        return [
            'echo "$LOG_PREFIX Downloading hobby installer from GitHub releases..."',
            "curl -L https://github.com/PostHog/posthog/releases/download/hobby-latest/hobby-installer -o hobby-installer",
            "chmod +x hobby-installer",
        ]

    def _build_user_data(self):
        """Build cloud-init user_data script with SSH pubkey in cloud-config"""
        cloud_config = """#cloud-config
runcmd:
  - set -e
"""
        # Sanitize inputs to prevent command injection
        safe_sha = shlex.quote(self.sha) if self.sha else "unknown"
        safe_hostname = shlex.quote(self.hostname)

        # Add runcmd commands with logging
        commands = [
            'LOG_PREFIX="[$(date +%Y-%m-%d_%H:%M:%S)]"',
            'echo "$LOG_PREFIX Cloud-init deployment starting"',
            "mkdir -p hobby",
            "cd hobby",
            'echo "$LOG_PREFIX Setting up needrestart config"',
            "sed -i \"s/#\\$nrconf{restart} = 'i';/\\$nrconf{restart} = 'a';/g\" /etc/needrestart/needrestart.conf",
            'echo "$LOG_PREFIX Cloning PostHog repository (shallow)"',
            "git init posthog",
            "cd posthog",
            "git remote add origin https://github.com/PostHog/posthog.git",
            f'echo "$LOG_PREFIX Fetching commit: {safe_sha}"',
            f"git fetch --depth 1 origin {safe_sha}",
            f'echo "$LOG_PREFIX Checking out commit: {safe_sha}"',
            "git checkout FETCH_HEAD",
            "CURRENT_COMMIT=$(git rev-parse HEAD)",
            'echo "$LOG_PREFIX Current commit: $CURRENT_COMMIT"',
            "cd ..",
            'echo "$LOG_PREFIX Waiting for docker image to be available on DockerHub..."',
            self._get_wait_for_image_script(),
            self._get_node_image_fallback_script(),
            *self._get_installer_commands(),
            'echo "$LOG_PREFIX Starting hobby installer (CI mode)"',
            f"./hobby-installer --ci --domain {safe_hostname} --version $CURRENT_COMMIT",
            "DEPLOY_EXIT=$?",
            'echo "$LOG_PREFIX Hobby installer exited with code: $DEPLOY_EXIT"',
            "exit $DEPLOY_EXIT",
        ]

        for cmd in commands:
            # YAML needs quotes around commands containing colons to avoid parsing as dict
            if ":" in cmd:
                # Escape inner quotes for YAML
                escaped_cmd = cmd.replace('"', '\\"')
                cloud_config += f'  - "{escaped_cmd}"\n'
            else:
                cloud_config += f"  - {cmd}\n"

        return cloud_config

    def block_until_droplet_is_started(self, timeout_minutes=10):
        if not self.droplet:
            return
        actions = self.droplet.get_actions()
        deadline = datetime.datetime.now() + datetime.timedelta(minutes=timeout_minutes)
        up = False
        while not up:
            if datetime.datetime.now() > deadline:
                raise TimeoutError(f"Droplet did not boot within {timeout_minutes} minutes")
            for action in actions:
                action.load()
                if action.status == "completed":
                    up = True
                    print(action.status)
                else:
                    print("Droplet not booted yet - waiting a bit", flush=True)
                    time.sleep(5)

    def get_public_ip(self, timeout_minutes=5):
        if not self.droplet:
            return
        ip = None
        deadline = datetime.datetime.now() + datetime.timedelta(minutes=timeout_minutes)
        while not ip:
            if datetime.datetime.now() > deadline:
                raise TimeoutError(f"Droplet did not get a public IP within {timeout_minutes} minutes")
            time.sleep(1)
            self.droplet.load()
            ip = self.droplet.ip_address
        print(f"Public IP found: {ip}")  # type: ignore
        return ip

    def create_droplet(self, ssh_enabled=False):
        keys = None
        if ssh_enabled:
            manager = digitalocean.Manager(token=self.token)
            keys = manager.get_all_sshkeys()

        # Build tags with branch, SHA, and PR info
        tags = ["ci", "ci-hobby"]
        if self.branch:
            # Sanitize branch name for tags (alphanumeric, hyphens, underscores only)
            safe_branch = self.branch.replace("/", "-").replace("_", "-")[:63]
            tags.append(f"branch:{safe_branch}")
        if self.sha:
            tags.append(f"sha:{self.sha[:7]}")
        if self.pr_number and self.pr_number != "unknown":
            tags.append(f"pr:{self.pr_number}")

        # Fallback candidates: try larger sizes first (PostHog needs ≥16 GB RAM),
        # then fall back across regions. sfo3 has had capacity issues since ~Mar 17 2026.
        fallback_candidates = list(
            dict.fromkeys(
                [
                    (self.region, FALLBACK_SIZE),
                    (self.region, self.size),
                    ("nyc3", FALLBACK_SIZE),
                    ("nyc3", self.size),
                    ("ams3", FALLBACK_SIZE),
                    ("ams3", self.size),
                ]
            )
        )

        last_error = None
        for region, size in fallback_candidates:
            print(f"Attempting droplet creation: region={region}, size={size}")
            droplet = digitalocean.Droplet(
                token=self.token,
                name=self.name,
                region=region,
                image=self.image,
                size_slug=size,
                user_data=self.user_data,
                ssh_keys=keys,
                tags=tags,
            )
            try:
                droplet.create()
                if region != self.region or size != self.size:
                    print(f"Droplet created with fallback: region={region}, size={size}")
                self.region = region
                self.size = size
                self.droplet = droplet
                return self.droplet
            except digitalocean.DataReadError as e:
                err_lower = str(e).lower()
                if "not available in this region" not in err_lower and "size is unavailable" not in err_lower:
                    raise
                print(f"Droplet creation failed (region={region}, size={size}): {e}")
                last_error = e

        raise RuntimeError(f"Droplet creation failed for all region/size combinations. Last error: {last_error}")

    def get_droplet_info(self):
        """Fetch droplet information from DigitalOcean API for debugging"""
        if not self.droplet or not self.token:
            return None
        try:
            self.droplet.load()
            return {
                "id": self.droplet.id,
                "name": self.droplet.name,
                "status": self.droplet.status,
                "ip": self.droplet.ip_address,
                "memory": self.droplet.memory,
                "vcpus": self.droplet.vcpus,
                "disk": self.droplet.disk,
                "created_at": self.droplet.created_at,
            }
        except Exception as e:
            print(f"Could not fetch droplet info: {e}")
            return None

    def run_ssh_command(self, command, timeout=60):
        """Execute a command on the droplet via SSH"""
        if not self.droplet or not self.ssh_private_key:
            raise ValueError("Droplet or SSH key not configured")

        import io

        import paramiko

        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Load private key from string (try Ed25519 first, then RSA)
            try:
                key = paramiko.Ed25519Key.from_private_key(io.StringIO(self.ssh_private_key))
            except paramiko.SSHException:
                key = paramiko.RSAKey.from_private_key(io.StringIO(self.ssh_private_key))

            # Connect to droplet
            client.connect(hostname=self.droplet.ip_address, username="root", pkey=key, timeout=timeout)

            # Execute command
            stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
            exit_status = stdout.channel.recv_exit_status()

            stdout_text = stdout.read().decode("utf-8")
            stderr_text = stderr.read().decode("utf-8")

            client.close()

            return {"exit_code": exit_status, "stdout": stdout_text, "stderr": stderr_text}
        except Exception as e:
            return {"exit_code": -1, "stdout": "", "stderr": f"SSH command failed: {str(e)}"}

    def upload_file(self, local_path: str, remote_path: str, timeout: int = 30) -> None:
        """Upload a local file to the droplet via SFTP."""
        if not self.droplet or not self.ssh_private_key:
            raise ValueError("Droplet or SSH key not configured")

        import io

        import paramiko

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            key = paramiko.Ed25519Key.from_private_key(io.StringIO(self.ssh_private_key))
        except paramiko.SSHException:
            key = paramiko.RSAKey.from_private_key(io.StringIO(self.ssh_private_key))

        client.connect(hostname=self.droplet.ip_address, username="root", pkey=key, timeout=timeout)
        sftp = client.open_sftp()
        sftp.put(local_path, remote_path)
        sftp.close()
        client.close()

    def generate_demo_data(self):
        """Generate demo data on the droplet."""
        if not self.droplet or not self.ssh_private_key:
            print("❌ Cannot generate demo data: missing droplet or SSH key", flush=True)
            return False

        print("🎲 Generating demo data (this may take a few minutes)...", flush=True)

        result = self.run_ssh_command(
            "cd /hobby && sudo -E docker-compose -f docker-compose.yml exec -T web python manage.py generate_demo_data",
            timeout=600,
        )

        if result["exit_code"] == 0:
            print("✅ Demo data generated", flush=True)
            return True

        print(f"❌ Demo data generation failed (exit {result['exit_code']})", flush=True)
        if result["stderr"]:
            print(f"   Error: {result['stderr']}", flush=True)
        return False

    def smoke_test_ingestion(self, timeout_seconds=180, poll_interval=10):
        if not self.droplet:
            return False, "No droplet configured"
        if not self.ssh_private_key:
            return False, "No SSH key configured"

        # nosemgrep: python.lang.security.audit.insecure-transport.requests.request-with-http.request-with-http
        base_url = f"http://{self.droplet.ip_address}"

        print("📝 Creating test user and fetching API keys via Django shell...", flush=True)
        script_path = os.path.join(os.path.dirname(__file__), "hobby-ci-setup-user.py")
        remote_script = "/tmp/hobby-ci-setup-user.py"
        try:
            self.upload_file(script_path, remote_script)
        except Exception as e:
            return False, f"Failed to upload setup script: {e}"

        cp_result = self.run_ssh_command(f"docker cp {remote_script} hobby-web-1:/tmp/setup.py", timeout=15)
        if cp_result["exit_code"] != 0:
            return False, f"Failed to copy setup script to container: {cp_result['stderr'][:200]}"
        result = self.run_ssh_command(
            "cd /hobby && sudo -E docker-compose -f docker-compose.yml exec -T web bash -c 'PYTHONPATH=/code:/python-runtime python /tmp/setup.py'",
            timeout=60,
        )
        if result["exit_code"] != 0:
            return (
                False,
                f"User setup failed (exit {result['exit_code']}): stderr={result['stderr'][:2000]} stdout={result['stdout'][:2000]}",
            )

        output_line = [line for line in result["stdout"].strip().split("\n") if "|||" in line]
        if not output_line:
            return False, f"Could not parse API keys from output: {result['stdout'][:200]}"
        project_api_token, personal_api_key = output_line[-1].split("|||")

        event_name = "hobby_ci_smoke_test"
        print(f"📤 Sending test event '{event_name}'...", flush=True)
        try:
            capture_resp = requests.post(
                f"{base_url}/capture/",  # nosemgrep: python.lang.security.audit.insecure-transport.requests.request-with-http.request-with-http
                json={
                    "api_key": project_api_token,
                    "event": event_name,
                    "properties": {"source": "hobby-ci"},
                    "distinct_id": "ci-test-user",
                },
                timeout=30,
            )
        except requests.RequestException as e:
            return False, f"Capture request failed: {e}"
        if capture_resp.status_code != 200:
            return False, f"Capture failed: HTTP {capture_resp.status_code} - {capture_resp.text[:200]}"

        print(f"⏳ Polling for event (timeout {timeout_seconds}s)...", flush=True)
        headers = {"Authorization": f"Bearer {personal_api_key}"}
        deadline = time.time() + timeout_seconds
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            try:
                events_resp = requests.get(
                    f"{base_url}/api/projects/@current/events/",  # nosemgrep: python.lang.security.audit.insecure-transport.requests.request-with-http.request-with-http
                    params={"event": event_name},
                    headers=headers,
                    timeout=10,
                )
                if events_resp.status_code == 200:
                    results = events_resp.json().get("results", [])
                    if len(results) > 0:
                        print(f"✅ Event found after {attempt} poll(s)", flush=True)
                        return True, "Event ingested successfully"
                    print(f"   Poll {attempt}: no events yet", flush=True)
                else:
                    print(f"   Poll {attempt}: HTTP {events_resp.status_code}", flush=True)
            except Exception as e:
                print(f"   Poll {attempt}: {type(e).__name__}", flush=True)
            time.sleep(poll_interval)

        return False, f"Event did not appear within {timeout_seconds}s ({attempt} polls)"

    @staticmethod
    def find_existing_droplet_for_pr(token, pr_number):
        """Find an existing droplet for a PR by tag"""
        if not pr_number or pr_number == "unknown":
            return None

        try:
            manager = digitalocean.Manager(token=token)
            tag_name = f"pr:{pr_number}"

            # Get all droplets with this tag
            tagged_droplets = manager.get_all_droplets(tag_name=tag_name)

            if tagged_droplets:
                # Return the first one (should only be one per PR)
                return tagged_droplets[0]
            return None
        except Exception as e:
            print(f"Error finding existing droplet: {e}")
            return None

    def update_existing_deployment(self, new_sha):
        """Update an existing droplet deployment with new code"""
        if not self.droplet:
            raise ValueError("No droplet configured")

        print(f"🔄 Updating existing deployment to SHA: {new_sha}")

        # Update repo checkout so compose files and other configs are current
        print("📦 Updating repo checkout...")
        update_repo_cmd = f"cd /hobby/posthog && git fetch origin {new_sha} && git checkout {new_sha}"
        result = self.run_ssh_command(update_repo_cmd, timeout=120)
        if result["exit_code"] != 0:
            print(f"⚠️ Failed to update repo checkout: {result['stderr']}")
        else:
            print("✅ Repo checkout updated")

        # Update .env file with new image tag
        update_env_cmd = (
            f"cd /hobby && sed -i 's/^POSTHOG_APP_TAG=.*/POSTHOG_APP_TAG={new_sha}/' .env && grep POSTHOG_APP_TAG .env"
        )
        result = self.run_ssh_command(update_env_cmd, timeout=30)
        if result["exit_code"] != 0:
            raise RuntimeError(f"Failed to update .env: {result['stderr']}")
        print(f"✅ Updated POSTHOG_APP_TAG to {new_sha}")

        # Resolve node image tag: ci-nodejs-container.yml tags as pr-<number> for PRs
        pr_tag = f"pr-{self.pr_number}" if self.pr_number and self.pr_number != "unknown" else None
        candidate_tag = pr_tag or new_sha
        print(f"🔍 Checking if node image exists with tag: {candidate_tag}...")
        check_node_cmd = f'curl -sf "https://hub.docker.com/v2/repositories/posthog/posthog-node/tags/{candidate_tag}" > /dev/null 2>&1'
        result = self.run_ssh_command(check_node_cmd, timeout=30)
        if result["exit_code"] == 0:
            node_tag = candidate_tag
            print(f"✅ Node image found, using tag: {candidate_tag}")
        else:
            node_tag = "latest"
            print(f"ℹ️ Node image not found for {candidate_tag}, falling back to tag: latest")

        # Update or add POSTHOG_NODE_TAG in .env
        update_node_tag_cmd = (
            f"cd /hobby && "
            f"if grep -q '^POSTHOG_NODE_TAG=' .env; then "
            f"  sed -i 's/^POSTHOG_NODE_TAG=.*/POSTHOG_NODE_TAG={node_tag}/' .env; "
            f"else "
            f"  echo 'POSTHOG_NODE_TAG={node_tag}' >> .env; "
            f"fi && grep POSTHOG_NODE_TAG .env"
        )
        result = self.run_ssh_command(update_node_tag_cmd, timeout=30)
        if result["exit_code"] != 0:
            raise RuntimeError(f"Failed to update POSTHOG_NODE_TAG: {result['stderr']}")
        print(f"✅ Updated POSTHOG_NODE_TAG to {node_tag}")

        # Update the baked-in image tags in docker-compose.yml.
        # The hobby-installer substitutes $POSTHOG_APP_TAG and $POSTHOG_NODE_TAG literally
        # into docker-compose.yml at install time, so updating .env alone has no effect on
        # which image docker-compose pull/up uses.
        print("📝 Updating baked-in image tags in docker-compose.yml...")
        update_compose_cmd = (
            f"cd /hobby && "
            f"sed -i 's|posthog/posthog:[a-f0-9]\\{{40\\}}|posthog/posthog:{new_sha}|g' docker-compose.yml && "
            f"sed -i 's|posthog/posthog-node:[^[:space:]]*|posthog/posthog-node:{node_tag}|g' docker-compose.yml"
        )
        result = self.run_ssh_command(update_compose_cmd, timeout=30)
        if result["exit_code"] != 0:
            raise RuntimeError(f"Failed to update docker-compose.yml: {result['stderr']}")
        print("✅ Updated docker-compose.yml image tags")

        # Sync docker-compose.base.yml from repo checkout so proxy config stays current
        print("📝 Syncing docker-compose.base.yml from repo...")
        sync_base_cmd = "cp /hobby/posthog/docker-compose.base.yml /hobby/docker-compose.base.yml"
        result = self.run_ssh_command(sync_base_cmd, timeout=30)
        if result["exit_code"] != 0:
            print(f"⚠️ Failed to sync docker-compose.base.yml: {result['stderr']}")
        else:
            print("✅ docker-compose.base.yml synced")

        # Pull new images with retry logic
        print("🐋 Pulling new Docker images...")
        pull_cmd = 'cd /hobby && for attempt in 1 2 3; do echo "Pull attempt $attempt/3"; docker-compose pull && break || { echo "Pull failed, waiting 30s..."; sleep 30; }; done'
        result = self.run_ssh_command(pull_cmd, timeout=800)
        if result["exit_code"] != 0:
            raise RuntimeError(f"Failed to pull images after 3 attempts: {result['stderr']}")
        print("✅ Images pulled successfully")

        # Restart services with new images
        print("🔄 Restarting services...")
        result = self.run_ssh_command("cd /hobby && docker-compose up -d", timeout=300)
        if result["exit_code"] != 0:
            raise RuntimeError(f"Failed to restart services: {result['stderr']}")
        print("✅ Services restarted")

        # Wait a moment for services to stabilize
        print("⏳ Waiting for services to stabilize...")
        self.run_ssh_command("sleep 10", timeout=15)

        print(f"✅ Deployment updated successfully")
        return True

    def get_droplet_kernel_logs(self):
        """Attempt to get kernel logs from droplet via API"""
        if not self.droplet or not self.token:
            return None
        try:
            # Try to get serial console output (requires the droplet to have it enabled)
            url = f"https://api.digitalocean.com/v2/droplets/{self.droplet.id}/console"
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return data.get("console_output")
        except Exception as e:
            print(f"Could not fetch kernel logs: {e}")
        return None

    def check_container_health(self):
        """Check if all containers are running and not in a restart loop.
        Returns: (all_healthy, unhealthy_containers, all_containers)
        """
        import json

        # Get container status with restart count using docker inspect
        output = self.run_command_on_droplet(
            'docker ps -q | xargs -r docker inspect --format \'{"Name":"{{.Name}}","State":"{{.State.Status}}","RestartCount":{{.RestartCount}},"StartedAt":"{{.State.StartedAt}}"}\' 2>/dev/null || echo "[]"',
            timeout=30,
        )

        print(f"  [debug] docker inspect output: {output[:500] if output else 'None'}...", flush=True)

        if not output or not output.strip() or output.strip() == "[]":
            print(f"  [debug] No container output - SSH may have failed", flush=True)
            return (False, [], [])

        try:
            containers = [json.loads(line) for line in output.strip().split("\n") if line and line != "[]"]
            if not containers:
                return (False, [], [])

            unhealthy = []
            for c in containers:
                container_name = c.get("Name", "unknown").lstrip("/")
                # Convert container name to docker-compose service name
                # e.g., 'hobby-cymbal-1' -> 'cymbal', 'hobby-property-defs-rs-1' -> 'property-defs-rs'
                import re

                match = re.match(r"^hobby-(.+)-\d+$", container_name)
                service_name = match.group(1) if match else container_name

                state = c.get("State", "")
                restart_count = c.get("RestartCount", 0)

                # Worker gets special handling - it may restart while waiting for migrations
                # Allow "restarting" state (between restart cycles) as long as under threshold
                if service_name == "worker":
                    max_restarts = 30
                    if state not in ("running", "restarting"):
                        unhealthy.append({"Service": service_name, "State": state, "RestartCount": restart_count})
                    elif restart_count >= max_restarts:
                        unhealthy.append(
                            {
                                "Service": service_name,
                                "State": f"restarted {restart_count}x",
                                "RestartCount": restart_count,
                            }
                        )
                # Other containers must be running and under restart threshold
                elif state != "running":
                    unhealthy.append({"Service": service_name, "State": state, "RestartCount": restart_count})
                elif restart_count >= 3:
                    unhealthy.append(
                        {
                            "Service": service_name,
                            "State": f"restarted {restart_count}x",
                            "RestartCount": restart_count,
                        }
                    )

            all_healthy = len(unhealthy) == 0 and len(containers) > 0

            return (all_healthy, unhealthy, containers)
        except Exception as e:
            print(f"  ⚠️  Could not parse container status: {e}", flush=True)
            return (False, [], [])

    def wait_for_cloud_init(
        self, timeout_minutes: int = 35, retry_interval: int = 15
    ) -> tuple[bool, dict, datetime.datetime | None]:
        """Poll until cloud-init finishes or the stack starts.

        Returns (success, failure_details, cloud_init_finished_at).
        """
        start_time = datetime.datetime.now()
        last_log_fetch = -30
        attempt = 0

        print(f"⏱️  Waiting up to {timeout_minutes}min for cloud-init", flush=True)

        while True:
            now = datetime.datetime.now()
            elapsed = (now - start_time).total_seconds()

            if now > start_time + datetime.timedelta(minutes=timeout_minutes):
                print(f"\n❌ Cloud-init timed out after {timeout_minutes} minutes", flush=True)
                return (
                    False,
                    {
                        "reason": "cloud_init_timeout",
                        "message": f"Cloud-init did not finish within {timeout_minutes} minutes",
                    },
                    None,
                )

            attempt += 1
            if attempt % 10 == 0:
                print(f"⏱️  Still waiting... (attempt {attempt}, elapsed {int(elapsed)}s)", flush=True)

            try:
                # nosemgrep: python.lang.security.audit.insecure-transport.requests.request-with-http.request-with-http
                r = requests.get(f"http://{self.droplet.ip_address}/_health", timeout=10)  # HTTP: avoid DNS/TLS in CI
                if r.status_code == 200:
                    print(f"  Health endpoint responding (HTTP 200)", flush=True)
                else:
                    print(f"  Instance not ready (HTTP {r.status_code})", flush=True)
            except Exception as e:
                print(f"  Connection failed: {type(e).__name__}", flush=True)

            if int(elapsed) - last_log_fetch > 60:
                finished, success, status = self.check_cloud_init_status()
                if finished and not success:
                    print("\n❌ Cloud-init deployment FAILED", flush=True)
                    return (
                        False,
                        {
                            "reason": "cloud_init_failed",
                            "message": "Cloud-init deployment failed",
                            "status": status.get("status") if status else None,
                            "errors": status.get("errors") if status else None,
                        },
                        None,
                    )

                if finished and success:
                    finished_at = datetime.datetime.now()
                    print(f"\n📋 Cloud-init completed successfully ({int(elapsed)}s elapsed)", flush=True)
                    return (True, {}, finished_at)

                logs = self.fetch_cloud_init_logs()
                # FRAGILE: these strings come from bin/hobby-installer/core/install.go
                # (~line 192 step name, ~line 198 detail). Changing them there breaks this.
                if logs and "Start PostHog stack" in logs and "started" in logs:
                    finished_at = datetime.datetime.now()
                    print(
                        f"\n📋 Stack started, skipping cloud-init health wait ({int(elapsed)}s elapsed)",
                        flush=True,
                    )
                    return (True, {}, finished_at)

                print("\n📋 Cloud-init progress:", flush=True)
                if logs:
                    for line in logs.strip().split("\n")[-10:]:
                        print(f"  {line}", flush=True)

                last_log_fetch = int(elapsed)
                print()

            time.sleep(retry_interval)

    def wait_for_health_check(
        self,
        cloud_init_finished_at: datetime.datetime,
        timeout_minutes: int = 35,
        retry_interval: int = 15,
        stability_period: int = 300,
        startup_grace_seconds: int = 300,
    ) -> tuple[bool, dict]:
        """Poll /_health until PostHog is stable.

        Returns (success, failure_details).
        """

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        start_time = datetime.datetime.now()
        deadline = start_time + datetime.timedelta(minutes=timeout_minutes)
        attempt = 0
        last_error = None
        http_502_count = 0
        connection_error_count = 0
        last_log_fetch = -30
        containers_healthy_since: datetime.datetime | None = None

        print(f"⏱️  Waiting up to {timeout_minutes}min for health check", flush=True)

        while True:
            now = datetime.datetime.now()
            elapsed = (now - start_time).total_seconds()

            past_deadline = now > deadline
            in_stability_window = containers_healthy_since is not None
            if past_deadline and not in_stability_window:
                print(f"\nFailure - health check timed out after {timeout_minutes} minutes", flush=True)
                return (
                    False,
                    {
                        "reason": "health_timeout",
                        "message": f"Health check did not pass within {timeout_minutes} minutes",
                        "connection_errors": connection_error_count,
                        "http_502_count": http_502_count,
                        "last_error": last_error,
                    },
                )

            attempt += 1
            if attempt % 10 == 0:
                print(f"⏱️  Still trying... (attempt {attempt}, elapsed {int(elapsed)}s)", flush=True)
            print(f"Trying to connect... (attempt {attempt})", flush=True)

            health_check_passed = False
            all_healthy = False
            try:
                # nosemgrep: python.lang.security.audit.insecure-transport.requests.request-with-http.request-with-http
                r = requests.get(f"http://{self.droplet.ip_address}/_health", timeout=10)  # HTTP: avoid DNS/TLS in CI
                if r.status_code == 200:
                    health_check_passed = True
                else:
                    if r.status_code == 502:
                        http_502_count += 1
                    print(f"Instance not ready (HTTP {r.status_code})", flush=True)
            except Exception as e:
                last_error = type(e).__name__
                connection_error_count += 1
                print(f"Connection failed: {type(e).__name__}", flush=True)

            if int(elapsed) - last_log_fetch > 60:
                print("\n🐳 Container status:", flush=True)
                _, stopped, containers = self.check_container_health()
                if containers:
                    running_count = len(containers) - len(stopped)
                    print(f"  Running: {running_count}/{len(containers)} containers", flush=True)

                if not health_check_passed:
                    self._print_container_logs()

                last_log_fetch = int(elapsed)
                print()

            all_healthy, stopped, containers = self.check_container_health()
            past_grace = (now - cloud_init_finished_at).total_seconds() > startup_grace_seconds
            if not all_healthy and stopped and past_grace:
                print(f"\n❌ Container health check failed - failing fast", flush=True)
                self._print_failing_container_diagnostics(stopped)
                unhealthy_list = [f"{c.get('Service')}: {c.get('State')}" for c in stopped]
                return (
                    False,
                    {
                        "reason": "container_unhealthy",
                        "message": "Container health check failed",
                        "unhealthy_containers": unhealthy_list,
                    },
                )

            if health_check_passed:
                if containers_healthy_since is None:
                    containers_healthy_since = datetime.datetime.now()
                    print(f"  ✅ All containers running, starting stability timer", flush=True)
                else:
                    stable_for = (datetime.datetime.now() - containers_healthy_since).total_seconds()
                    if stable_for >= stability_period:
                        total = (datetime.datetime.now() - cloud_init_finished_at).total_seconds()
                        print(
                            f"✅ Success - health check passed and containers stable for {int(stable_for)}s",
                            flush=True,
                        )
                        print(f"   Health check phase took: {int(total)}s", flush=True)
                        return (True, {})
                    else:
                        print(
                            f"  Health check passed, containers stable for {int(stable_for)}s / {stability_period}s",
                            flush=True,
                        )
            elif not all_healthy:
                containers_healthy_since = None

            time.sleep(retry_interval)

    def _print_container_logs(self) -> None:
        """Print recent logs from web, worker, and proxy containers."""
        for name, tail in [("web", 15), ("worker", 10), ("proxy", 5)]:
            print(f"\n📋 {name} container logs (last {tail} lines):", flush=True)
            result = self.run_ssh_command(f"docker logs --tail={tail} hobby-{name}-1 2>&1 || true", timeout=15)
            if result["exit_code"] == 0 and result["stdout"].strip():
                for line in result["stdout"].strip().split("\n"):
                    print(f"  [{name}] {line}", flush=True)

    def _print_failing_container_diagnostics(self, stopped_containers: list[dict]) -> None:
        """Print diagnostic info for failing containers."""
        failing_names = []
        for c in stopped_containers:
            container_info = f"{c.get('Service')}: {c.get('State')}"
            failing_names.append(c.get("Service", "unknown"))
            print(f"    ❌ {container_info}", flush=True)

        self.fetch_and_print_failing_container_logs(failing_names)

        print(f"\n📋 Checking kafka-init status:", flush=True)
        kafka_init_result = self.run_ssh_command(
            "docker ps -a --filter name=hobby-kafka-init --format '{{.Names}}: {{.Status}}'", timeout=15
        )
        if kafka_init_result["exit_code"] == 0 and kafka_init_result["stdout"]:
            print(f"    {kafka_init_result['stdout'].strip()}", flush=True)
        kafka_logs_result = self.run_ssh_command("docker logs hobby-kafka-init-1 2>&1 || true", timeout=15)
        if kafka_logs_result["exit_code"] == 0 and kafka_logs_result["stdout"]:
            for line in kafka_logs_result["stdout"].strip().split("\n")[-20:]:
                print(f"    {line}", flush=True)

        print(f"\n📋 Checking for OOM kills:", flush=True)
        oom_result = self.run_ssh_command("dmesg | grep -i 'oom\\|killed process' | tail -10 || true", timeout=15)
        if oom_result["exit_code"] == 0 and oom_result["stdout"].strip():
            for line in oom_result["stdout"].strip().split("\n"):
                print(f"    {line}", flush=True)
        else:
            print(f"    No OOM kills found", flush=True)

        print(f"\n📋 Memory usage:", flush=True)
        mem_result = self.run_ssh_command("free -h", timeout=15)
        if mem_result["exit_code"] == 0 and mem_result["stdout"]:
            for line in mem_result["stdout"].strip().split("\n"):
                print(f"    {line}", flush=True)

        print(f"\n📍 For debugging, SSH to: ssh root@{self.droplet.ip_address}", flush=True)

    def test_deployment_with_details(
        self,
        cloud_init_timeout=35,
        health_timeout=35,
        retry_interval=15,
        stability_period=300,
        startup_grace_seconds=300,
    ) -> tuple[bool, dict]:
        """Wait for cloud-init then health check, with separate timeouts for each phase."""
        if not self.hostname:
            return (False, {"reason": "no_hostname", "message": "No hostname configured"})

        print(
            f"⏱️  Timeouts: cloud-init {cloud_init_timeout}min, health check {health_timeout}min after cloud-init",
            flush=True,
        )

        cloud_init_ok, details, finished_at = self.wait_for_cloud_init(cloud_init_timeout, retry_interval)
        if not cloud_init_ok:
            return (False, details)

        health_ok, details = self.wait_for_health_check(
            finished_at, health_timeout, retry_interval, stability_period, startup_grace_seconds
        )
        return (health_ok, details)

    def create_dns_entry(self, type, name, data, ttl=30):
        self.domain = digitalocean.Domain(token=self.token, name=DOMAIN)
        self.record = self.domain.create_new_domain_record(type=type, name=name, data=data, ttl=ttl)
        return self.record

    def create_dns_entry_for_instance(self):
        if not self.droplet:
            return
        self.record = self.create_dns_entry(type="A", name=self.name, data=self.get_public_ip())
        return self.record

    def destroy_self(self, retries=3):
        if not self.droplet or not self.domain or not self.record:
            return
        droplet_id = self.droplet.id
        record_id = self.record["domain_record"]["id"]
        self.destroy_environment(droplet_id=droplet_id, record_id=record_id, retries=retries)

    @staticmethod
    def destroy_environment(droplet_id, record_id, retries=3):
        """Destroy droplet and DNS record with retries."""
        token = os.getenv("DIGITALOCEAN_TOKEN")
        droplet = digitalocean.Droplet(token=token, id=droplet_id)
        domain = digitalocean.Domain(token=token, name=DOMAIN)

        def destroy_with_retry(name, destroy_fn):
            for attempt in range(1, retries + 2):
                try:
                    destroy_fn()
                    print(f"✅ {name} destroyed")
                    return True
                except digitalocean.NotFoundError:
                    print(f"✅ {name} not found (already cleaned up)")
                    return True
                except Exception as e:
                    print(f"⚠️  Attempt {attempt}/{retries + 1} - Could not destroy {name}: {type(e).__name__}")
                    if attempt <= retries:
                        time.sleep(2)
            print(f"❌ Failed to destroy {name} after {retries + 1} attempts")
            return False

        print("Destroying the droplet")
        droplet_destroyed = destroy_with_retry("Droplet", droplet.destroy)

        print("Destroying the DNS entry")
        dns_destroyed = destroy_with_retry("DNS record", lambda: domain.delete_domain_record(id=record_id))

        if not droplet_destroyed or not dns_destroyed:
            failed = []
            if not droplet_destroyed:
                failed.append(f"droplet {droplet_id}")
            if not dns_destroyed:
                failed.append(f"DNS record {record_id}")
            raise Exception(f"⚠️  Failed to destroy {' and '.join(failed)} - manual cleanup may be required")

        print("\n✅ Cleanup completed")

    @staticmethod
    def find_dns_record_for_ip(token, ip_address):
        """Find DNS A record matching the given IP address."""
        try:
            domain = digitalocean.Domain(token=token, name=DOMAIN)
            for record in domain.get_records():
                if record.type == "A" and record.data == ip_address:
                    return record.id
        except Exception as e:
            print(f"Could not find DNS record: {e}")
        return None

    def run_command_on_droplet(self, command, timeout=60):
        """Run a command on the droplet via SSH and return stdout, or None on failure."""
        if not self.droplet or not self.ssh_private_key:
            return None
        result = self.run_ssh_command(command, timeout=timeout)
        return result["stdout"] if result["exit_code"] == 0 else None

    def fetch_cloud_init_logs(self):
        """Fetch cloud-init logs via SSH."""
        return self.run_command_on_droplet("cat /var/log/cloud-init-output.log", timeout=30)

    def fetch_and_print_failing_container_logs(self, failing_containers, tail=100):
        """Fetch and print logs for failing containers, and save to files."""
        if not failing_containers:
            return

        for container in failing_containers:
            print(f"\n📋 Logs for {container}:", flush=True)

            # First, get container inspect info for exit code and OOM status
            inspect_cmd = f"docker inspect hobby-{container}-1 --format '{{{{.State.ExitCode}}}} {{{{.State.OOMKilled}}}} {{{{.State.Error}}}}' 2>&1 || true"
            inspect_result = self.run_ssh_command(inspect_cmd, timeout=15)
            if inspect_result["exit_code"] == 0 and inspect_result["stdout"].strip():
                print(f"    [container state] {inspect_result['stdout'].strip()}", flush=True)

            # Use docker logs directly - works better for restarting containers
            logs_cmd = f"docker logs --tail={tail} hobby-{container}-1 2>&1 || true"
            print(f"    [debug] Running: {logs_cmd}", flush=True)
            result = self.run_ssh_command(logs_cmd, timeout=30)
            print(
                f"    [debug] Exit code: {result['exit_code']}, stdout len: {len(result.get('stdout', ''))}", flush=True
            )
            container_logs = result["stdout"] if result["exit_code"] == 0 else None

            if container_logs:
                # Print last 50 lines to console
                log_lines = container_logs.strip().split("\n")[-50:]
                for log_line in log_lines:
                    print(f"    {log_line}", flush=True)

                # Save full logs to file for artifact upload
                safe_name = container.replace("/", "-").replace(" ", "_")
                log_path = f"/tmp/container-{safe_name}.log"
                try:
                    with open(log_path, "w") as f:
                        f.write(container_logs)
                    print(f"    (Full logs saved to {log_path})", flush=True)
                except Exception as e:
                    print(f"    ⚠️  Could not save logs: {e}", flush=True)

                # Search for errors in the full logs
                print(f"\n📋 Searching for errors in {container} logs:", flush=True)
                error_cmd = f"docker logs hobby-{container}-1 2>&1 | grep -i -E 'error|exception|traceback|failed|killed|signal|exited|docker-worker-celery' | tail -30 || true"
                error_result = self.run_ssh_command(error_cmd, timeout=30)
                if error_result["exit_code"] == 0 and error_result["stdout"].strip():
                    for line in error_result["stdout"].strip().split("\n"):
                        print(f"    ❌ {line}", flush=True)
                else:
                    print(f"    No obvious errors found", flush=True)

                # Check docker events for the container to see restart reasons
                print(f"\n📋 Docker events for {container} (last 5 mins):", flush=True)
                events_cmd = f"docker events --filter container=hobby-{container}-1 --since 5m --until 0s 2>&1 | head -20 || true"
                events_result = self.run_ssh_command(events_cmd, timeout=15)
                if events_result["exit_code"] == 0 and events_result["stdout"].strip():
                    for line in events_result["stdout"].strip().split("\n"):
                        print(f"    {line}", flush=True)
                else:
                    print(f"    No events captured", flush=True)

                # Check full container state including FinishedAt
                print(f"\n📋 Full container state for {container}:", flush=True)
                state_cmd = f"docker inspect hobby-{container}-1 --format '{{{{json .State}}}}' 2>&1 | python3 -m json.tool || true"
                state_result = self.run_ssh_command(state_cmd, timeout=15)
                if state_result["exit_code"] == 0 and state_result["stdout"].strip():
                    for line in state_result["stdout"].strip().split("\n")[:15]:
                        print(f"    {line}", flush=True)
            else:
                print(f"    (no logs available)", flush=True)

    def check_cloud_init_status(self):
        """Returns: (finished, success, status_dict)"""
        import json

        if not self.droplet or not self.ssh_private_key:
            return (False, False, None)

        try:
            result = self.run_ssh_command("cloud-init status --format=json", timeout=15)
            if result["exit_code"] != 0:
                return (False, False, None)

            status = json.loads(result["stdout"])
            finished = status.get("status") in ["done", "error"]
            success = status.get("status") == "done" and not status.get("errors")
            return (finished, success, status)
        except Exception:
            return (False, False, None)

    def export_droplet(self):
        if not self.droplet:
            print("Droplet not found. Exiting")
            exit(1)
        if not self.record:
            print("DNS record not found. Exiting")
            exit(1)
        record_id = self.record["domain_record"]["id"]
        record_name = self.record["domain_record"]["name"]
        droplet_id = self.droplet.id
        ip_address = self.droplet.ip_address

        print(f"Exporting the droplet ID: {self.droplet.id} and DNS record ID: {record_id} for name {self.name}")

        # Save to file for debugging on failure
        with open("/tmp/droplet_info.txt", "w") as f:
            f.write(f"Droplet ID: {droplet_id}\n")
            f.write(f"Droplet IP: {ip_address}\n")
            f.write(f"DNS Record ID: {record_id}\n")
            f.write(f"DNS Record Name: {record_name}\n")
            f.write(f"SSH: ssh root@{ip_address}\n")
            f.write(f"URL: https://{record_name}.posthog.cc\n")

        # Export to GitHub env
        env_file_name = os.getenv("GITHUB_ENV")
        with open(env_file_name, "a") as env_file:
            env_file.write(f"HOBBY_DROPLET_ID={droplet_id}\n")
            env_file.write(f"HOBBY_DROPLET_IP={ip_address}\n")
            env_file.write(f"HOBBY_DNS_RECORD_ID={record_id}\n")
            env_file.write(f"HOBBY_DNS_RECORD_NAME={record_name}\n")
            env_file.write(f"HOBBY_NAME={self.name}\n")
            env_file.write("HOBBY_DROPLET_NEW=true\n")

    def ensure_droplet(self, ssh_enabled=True):
        self.create_droplet(ssh_enabled=ssh_enabled)
        self.block_until_droplet_is_started()
        self.create_dns_entry_for_instance()
        self.export_droplet()


COMMENT_MARKER = "<!-- hobby-smoke-test -->"


@dataclass(frozen=True)
class PRCommentContext:
    pr_number: str
    gh_token: str
    run_id: str | None = None
    run_attempt: str | None = None

    @classmethod
    def from_env(cls) -> "PRCommentContext | None":
        pr_number = os.environ.get("PR_NUMBER")
        gh_token = os.environ.get("GH_TOKEN")
        if not pr_number or not gh_token:
            return None
        return cls(
            pr_number=pr_number,
            gh_token=gh_token,
            run_id=os.environ.get("RUN_ID"),
            run_attempt=os.environ.get("RUN_ATTEMPT"),
        )


def update_smoke_test_comment(
    ctx: PRCommentContext,
    success: bool,
    failure_details: dict,
) -> None:
    """Update or create a smoke test comment on the PR.

    - Only one comment per PR (edit existing if present)
    - Detect flapping if previous failure and now success
    """
    headers = {
        "Authorization": f"token {ctx.gh_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    repo = "PostHog/posthog"

    # Find existing comment and parse failure count
    existing_comment = None
    previous_was_failure = False
    previous_failure_count = 0
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{repo}/issues/{ctx.pr_number}/comments",
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            for comment in resp.json():
                body = comment.get("body", "")
                if COMMENT_MARKER in body:
                    existing_comment = comment
                    previous_was_failure = "❌" in body
                    # Parse previous failure count
                    import re

                    match = re.search(r"Consecutive failures: (\d+)", body)
                    if match:
                        previous_failure_count = int(match.group(1))
                    elif previous_was_failure:
                        previous_failure_count = 1
                    break
    except Exception as e:
        print(f"⚠️  Could not fetch existing comments: {e}", flush=True)

    # Build run link
    run_link = ""
    if ctx.run_id:
        attempt_suffix = f"/attempts/{ctx.run_attempt}" if ctx.run_attempt and ctx.run_attempt != "1" else ""
        run_link = f"https://github.com/{repo}/actions/runs/{ctx.run_id}{attempt_suffix}"

    # Build comment body
    failure_count = 0
    if success:
        if previous_was_failure:
            # Flapping: was failing, now passing
            status_emoji = "⚠️"
            status_text = "FLAPPING"
            body_content = (
                f"Test passed after {previous_failure_count} consecutive failure(s). This may indicate flaky behavior.\n\n"
                "The hobby deployment smoke test is now passing, but was failing on previous runs."
            )
        else:
            status_emoji = "✅"
            status_text = "PASSED"
            body_content = "Hobby deployment smoke test passed successfully."
    else:
        status_emoji = "❌"
        status_text = "FAILED"
        failure_count = previous_failure_count + 1
        reason = failure_details.get("reason", "unknown")
        message = failure_details.get("message", "Unknown failure")

        body_content = f"**Failing fast because:** {message}\n\n"

        if reason == "container_unhealthy":
            unhealthy = failure_details.get("unhealthy_containers", [])
            if unhealthy:
                body_content += "**Unhealthy containers:**\n"
                for container in unhealthy:
                    body_content += f"- `{container}`\n"
        elif reason == "cloud_init_failed":
            errors = failure_details.get("errors")
            if errors:
                body_content += f"**Errors:** {errors}\n"
        elif reason == "timeout":
            body_content += f"**Connection errors:** {failure_details.get('connection_errors', 0)}\n"
            body_content += f"**HTTP 502 count:** {failure_details.get('http_502_count', 0)}\n"
            if failure_details.get("last_error"):
                body_content += f"**Last error:** {failure_details.get('last_error')}\n"

    # Build footer
    footer_parts = [f"[Run {ctx.run_id}]({run_link})" if run_link else None]
    if failure_count > 0:
        footer_parts.append(f"Consecutive failures: {failure_count}")
    footer = " | ".join(p for p in footer_parts if p)

    comment_body = f"""{COMMENT_MARKER}
## {status_emoji} Hobby deploy smoke test: {status_text}

{body_content}

---
<sub>{footer}</sub>
"""

    # Create or update comment
    try:
        if existing_comment:
            resp = requests.patch(
                existing_comment["url"],
                headers=headers,
                json={"body": comment_body},
                timeout=10,
            )
            if resp.status_code == 200:
                print(f"✅ Updated smoke test comment on PR #{ctx.pr_number}", flush=True)
            else:
                print(f"⚠️  Failed to update comment: {resp.status_code}", flush=True)
        else:
            resp = requests.post(
                f"https://api.github.com/repos/{repo}/issues/{ctx.pr_number}/comments",
                headers=headers,
                json={"body": comment_body},
                timeout=10,
            )
            if resp.status_code == 201:
                print(f"✅ Created smoke test comment on PR #{ctx.pr_number}", flush=True)
            else:
                print(f"⚠️  Failed to create comment: {resp.status_code}", flush=True)
    except Exception as e:
        print(f"⚠️  Could not update PR comment: {e}", flush=True)


def main():
    command = sys.argv[1]
    if command == "create":
        if len(sys.argv) < 6:
            print("Please provide: branch, run_id, sha, pr_number")
            exit(1)
        branch = sys.argv[2]
        run_id = sys.argv[3]
        sha = sys.argv[4]
        pr_number = sys.argv[5]

        # Check if preview mode is enabled
        preview_mode = os.environ.get("PREVIEW_MODE", "false").lower() == "true"

        if preview_mode and pr_number != "unknown":
            # Preview mode: try to reuse existing droplet
            print(f"🔄 Preview mode enabled - checking for existing droplet for PR #{pr_number}", flush=True)
            token = os.environ.get("DIGITALOCEAN_TOKEN")
            existing_droplet = HobbyTester.find_existing_droplet_for_pr(token, pr_number)

            if existing_droplet:
                print(f"✅ Found existing droplet: {existing_droplet.name} (ID: {existing_droplet.id})", flush=True)
                print(f"  IP: {existing_droplet.ip_address}", flush=True)
                print(f"  Updating to SHA: {sha[:7]}", flush=True)

                # Use SSH key from secrets for accessing existing droplet
                ssh_key = os.environ.get("DIGITALOCEAN_SSH_PRIVATE_KEY")
                if not ssh_key:
                    print("❌ DIGITALOCEAN_SSH_PRIVATE_KEY not set - cannot update existing droplet", flush=True)
                    exit(1)

                # Create HobbyTester instance with existing droplet and deploy key
                ht = HobbyTester(
                    branch=branch,
                    name=existing_droplet.name,
                    sha=sha,
                    pr_number=pr_number,
                    droplet_id=existing_droplet.id,
                    ssh_private_key=ssh_key,
                )
                ht.droplet = existing_droplet

                # Update deployment
                ht.update_existing_deployment(sha)

                # Export minimal info for test step
                env_file_name = os.getenv("GITHUB_ENV")
                if env_file_name:
                    with open(env_file_name, "a") as env_file:
                        env_file.write(f"HOBBY_DROPLET_ID={existing_droplet.id}\n")
                        env_file.write(f"HOBBY_DROPLET_IP={existing_droplet.ip_address}\n")
                        env_file.write(f"HOBBY_NAME={existing_droplet.name}\n")
                        env_file.write("HOBBY_DROPLET_NEW=false\n")

                # Write droplet info file for GitHub deployment URL
                with open("/tmp/droplet_info.txt", "w") as f:
                    f.write(f"Droplet ID: {existing_droplet.id}\n")
                    f.write(f"Droplet IP: {existing_droplet.ip_address}\n")
                    f.write(f"SSH: ssh root@{existing_droplet.ip_address}\n")
                    f.write(f"URL: https://{ht.hostname}\n")

                print(f"✅ Preview deployment updated successfully", flush=True)
                print(f"🌐 URL: https://{ht.hostname}", flush=True)
            else:
                print(f"ℹ️  No existing droplet found - creating new one", flush=True)
                # Use stable PR-based name for preview deployments
                name = f"do-ci-hobby-pr-{pr_number}"
                print(f"Creating preview droplet for PR #{pr_number}", flush=True)
                print(f"  Branch: {branch}", flush=True)
                print(f"  SHA: {sha[:7]}", flush=True)
                print(f"  Droplet name: {name}", flush=True)
                ht = HobbyTester(
                    branch=branch,
                    name=name,
                    sha=sha,
                    pr_number=pr_number,
                )
                ht.ensure_droplet(ssh_enabled=True)
                print(
                    "Preview instance has started. You will be able to access it here after PostHog boots (~15 minutes):",
                    flush=True,
                )
                print(f"🌐 URL: https://{ht.hostname}", flush=True)
        else:
            # Smoke test mode: always create new ephemeral droplet
            # First, check if there's an orphaned preview droplet from a removed label
            token = os.environ.get("DIGITALOCEAN_TOKEN")
            if pr_number != "unknown":
                orphaned_droplet = HobbyTester.find_existing_droplet_for_pr(token, pr_number)
                if orphaned_droplet:
                    print(f"🧹 Found orphaned preview droplet for PR #{pr_number} - cleaning up", flush=True)
                    print(f"   (label was likely removed)", flush=True)
                    try:
                        record_id = HobbyTester.find_dns_record_for_ip(token, orphaned_droplet.ip_address)
                        HobbyTester.destroy_environment(droplet_id=orphaned_droplet.id, record_id=record_id)
                        print(f"✅ Cleaned up orphaned droplet", flush=True)
                    except Exception as e:
                        print(f"⚠️  Could not cleanup orphaned droplet: {e}", flush=True)

            name = f"do-ci-hobby-{run_id}"
            print(f"🧪 Smoke test mode - creating ephemeral droplet", flush=True)
            print(f"  Branch: {branch}", flush=True)
            print(f"  SHA: {sha[:7]}", flush=True)
            print(f"  PR: #{pr_number if pr_number != 'unknown' else 'N/A'}", flush=True)
            print(f"  Droplet name: {name}", flush=True)
            ht = HobbyTester(
                branch=branch,
                name=name,
                sha=sha,
                pr_number=pr_number,
            )
            ht.ensure_droplet(ssh_enabled=True)
            print(
                "Instance has started. You will be able to access it here after PostHog boots (~15 minutes):",
                flush=True,
            )
            print(f"https://{ht.hostname}", flush=True)

    if command == "destroy":
        print("Destroying droplet on Digitalocean for testing Hobby Deployment")
        droplet_id = os.environ.get("HOBBY_DROPLET_ID")
        domain_record_id = os.environ.get("HOBBY_DNS_RECORD_ID")
        print(f"Droplet ID: {droplet_id}")
        print(f"Record ID: {domain_record_id}")
        HobbyTester.destroy_environment(droplet_id=droplet_id, record_id=domain_record_id)

    if command == "fetch-logs":
        print("Fetching logs from droplet", flush=True)
        droplet_id = os.environ.get("HOBBY_DROPLET_ID")

        ht = HobbyTester(droplet_id=droplet_id)

        # Fetch and save cloud-init logs
        print("Fetching cloud-init logs...", flush=True)
        logs = ht.fetch_cloud_init_logs()
        if logs:
            artifact_path = "/tmp/cloud-init-output.log"
            with open(artifact_path, "w") as f:
                f.write(logs)
            print(f"Logs saved to {artifact_path} ({len(logs)} bytes)", flush=True)
        else:
            print("Could not fetch cloud-init logs", flush=True)

        # Fetch all docker-compose logs in one go
        print("Fetching all docker-compose logs...", flush=True)
        try:
            result = ht.run_command_on_droplet(
                "cd /hobby && sudo -E docker-compose -f docker-compose.yml logs --tail=100 --no-color 2>&1 | head -5000",
                timeout=120,
            )
            if result:
                log_path = "/tmp/docker-compose-logs.txt"
                with open(log_path, "w") as f:
                    f.write(result)
                print(f"Docker logs saved to {log_path} ({len(result)} bytes)", flush=True)
        except Exception as e:
            print(f"Could not fetch docker logs: {e}", flush=True)

    if command == "test":
        name = os.environ.get("HOBBY_NAME")
        record_id = os.environ.get("HOBBY_DNS_RECORD_ID")
        droplet_id = os.environ.get("HOBBY_DROPLET_ID")
        ssh_key = os.environ.get("DIGITALOCEAN_SSH_PRIVATE_KEY")

        print("Waiting for deployment to become healthy", flush=True)
        print(f"Record ID: {record_id}", flush=True)
        print(f"Droplet ID: {droplet_id}", flush=True)
        print(f"SSH key available: {bool(ssh_key)}", flush=True)

        if not ssh_key:
            print("⚠️  WARNING: No SSH key - cannot detect cloud-init failures early!", flush=True)

        ht = HobbyTester(
            name=name,
            record_id=record_id,
            droplet_id=droplet_id,
            ssh_private_key=ssh_key,
        )
        preview_mode = os.environ.get("PREVIEW_MODE", "false") == "true"
        stability = 300 if preview_mode else 60
        health_success, failure_details = ht.test_deployment_with_details(stability_period=stability)

        pr_ctx = PRCommentContext.from_env()
        if pr_ctx:
            update_smoke_test_comment(
                ctx=pr_ctx,
                success=health_success,
                failure_details=failure_details,
            )

        if health_success:
            print("We succeeded", flush=True)
            exit()
        else:
            print("We failed", flush=True)
            exit(1)

    if command == "wait-for-cloud-init":
        name = os.environ.get("HOBBY_NAME")
        record_id = os.environ.get("HOBBY_DNS_RECORD_ID")
        droplet_id = os.environ.get("HOBBY_DROPLET_ID")
        ssh_key = os.environ.get("DIGITALOCEAN_SSH_PRIVATE_KEY")

        ht = HobbyTester(name=name, record_id=record_id, droplet_id=droplet_id, ssh_private_key=ssh_key)
        success, details, finished_at = ht.wait_for_cloud_init()

        github_env = os.environ.get("GITHUB_ENV")
        if github_env:
            with open(github_env, "a") as f:
                f.write(f"CLOUD_INIT_OK={'true' if success else 'false'}\n")
                if finished_at:
                    f.write(f"CLOUD_INIT_FINISHED_AT={finished_at.isoformat()}\n")

        pr_ctx = PRCommentContext.from_env()
        if pr_ctx and not success:
            update_smoke_test_comment(ctx=pr_ctx, success=False, failure_details=details)

        exit(0 if success else 1)

    if command == "wait-for-health":
        name = os.environ.get("HOBBY_NAME")
        record_id = os.environ.get("HOBBY_DNS_RECORD_ID")
        droplet_id = os.environ.get("HOBBY_DROPLET_ID")
        ssh_key = os.environ.get("DIGITALOCEAN_SSH_PRIVATE_KEY")

        finished_at_str = os.environ.get("CLOUD_INIT_FINISHED_AT")
        if not finished_at_str:
            print("❌ CLOUD_INIT_FINISHED_AT not set", flush=True)
            exit(1)
        finished_at = datetime.datetime.fromisoformat(finished_at_str)

        ht = HobbyTester(name=name, record_id=record_id, droplet_id=droplet_id, ssh_private_key=ssh_key)
        preview_mode = os.environ.get("PREVIEW_MODE", "false") == "true"
        stability = 300 if preview_mode else 60
        success, details = ht.wait_for_health_check(finished_at, stability_period=stability)

        pr_ctx = PRCommentContext.from_env()
        if pr_ctx:
            update_smoke_test_comment(ctx=pr_ctx, success=success, failure_details=details)

        exit(0 if success else 1)

    if command == "generate-demo-data":
        print("Generating demo data on droplet", flush=True)
        droplet_id = os.environ.get("HOBBY_DROPLET_ID")

        ht = HobbyTester(droplet_id=droplet_id)
        success = ht.generate_demo_data()
        exit(0 if success else 1)

    if command == "smoke-test-ingestion":
        print("Running event ingestion smoke test", flush=True)
        droplet_id = os.environ.get("HOBBY_DROPLET_ID")

        ht = HobbyTester(droplet_id=droplet_id)
        success, message = ht.smoke_test_ingestion()
        print(f"{'✅' if success else '❌'} {message}", flush=True)
        exit(0 if success else 1)

    if command == "cleanup-stale":
        print("Cleaning up stale hobby preview droplets", flush=True)
        max_inactive_days = int(os.environ.get("MAX_INACTIVE_DAYS", "7"))
        dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
        gh_token = os.environ.get("GH_TOKEN", "")

        if dry_run:
            print("🔍 DRY RUN - no changes will be made", flush=True)

        if not gh_token:
            print("⚠️  GH_TOKEN not set - cannot check PR status, will only use droplet age")

        token = os.environ.get("DIGITALOCEAN_TOKEN")
        if not token:
            print("❌ DIGITALOCEAN_TOKEN not set")
            exit(1)

        manager = digitalocean.Manager(token=token)
        all_droplets = manager.get_all_droplets()
        now = datetime.datetime.now(datetime.UTC)
        cleaned = 0
        cleaned_prs: list[str] = []

        for droplet in all_droplets:
            # Find droplets with pr:* tags (hobby previews)
            pr_tag = None
            for tag in droplet.tags:
                if tag.startswith("pr:"):
                    pr_tag = tag
                    break

            if not pr_tag:
                continue

            pr_number = pr_tag.split(":")[1]
            droplet_created = datetime.datetime.fromisoformat(droplet.created_at.replace("Z", "+00:00"))
            droplet_age_days = (now - droplet_created).days

            print(f"\n📦 Droplet: {droplet.name} (ID: {droplet.id})")
            print(f"   PR: #{pr_number}, Droplet age: {droplet_age_days} days")

            should_destroy = False
            reason = ""

            # Check PR status and activity (requires GH_TOKEN)
            if gh_token:
                try:
                    headers = {"Authorization": f"token {gh_token}", "Accept": "application/vnd.github.v3+json"}
                    resp = requests.get(
                        f"https://api.github.com/repos/PostHog/posthog/pulls/{pr_number}",
                        headers=headers,
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        pr_data = resp.json()
                        pr_state = pr_data.get("state")

                        if pr_state == "closed":
                            should_destroy = True
                            reason = "PR is closed"
                        else:
                            # PR is open - check if it still has hobby-preview label
                            labels = [label.get("name", "").lower() for label in pr_data.get("labels", [])]
                            has_preview_label = "hobby-preview" in labels

                            if not has_preview_label:
                                should_destroy = True
                                reason = "PR no longer has hobby-preview label"
                            else:
                                # PR is open with label - check last activity
                                updated_at = pr_data.get("updated_at")
                                if updated_at:
                                    last_activity = datetime.datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                                    inactive_days = (now - last_activity).days
                                    print(f"   Last PR activity: {inactive_days} days ago")

                                    if inactive_days >= max_inactive_days:
                                        should_destroy = True
                                        reason = f"PR inactive for {inactive_days} days"
                    elif resp.status_code == 404:
                        should_destroy = True
                        reason = "PR not found"
                except Exception as e:
                    print(f"   ⚠️  Could not check PR status: {e}")
            else:
                # Fallback: use droplet age if no GH_TOKEN
                if droplet_age_days >= max_inactive_days:
                    should_destroy = True
                    reason = f"droplet older than {max_inactive_days} days (no GH_TOKEN to check PR)"

            if should_destroy:
                print(f"   🗑️  Will destroy: {reason}")
                if not dry_run:
                    try:
                        record_id = HobbyTester.find_dns_record_for_ip(token, droplet.ip_address)
                        HobbyTester.destroy_environment(droplet_id=droplet.id, record_id=record_id)
                        cleaned += 1
                        cleaned_prs.append(pr_number)
                    except Exception as e:
                        print(f"   ❌ Failed to destroy: {e}")
            else:
                print(f"   ✅ Keeping (PR open and active)")

        print(f"\n{'Would clean' if dry_run else 'Cleaned'} {cleaned} droplet(s)")

        # Output cleaned PR numbers for GitHub deployment cleanup
        if cleaned_prs:
            print(f"Cleaned PRs: {','.join(cleaned_prs)}")
            # Write to file for workflow to pick up
            with open("/tmp/cleaned_prs.txt", "w") as f:
                f.write(",".join(cleaned_prs))

    if command == "destroy-pr":
        # Destroy droplet for a specific PR number
        pr_number = os.environ.get("PR_NUMBER")
        if not pr_number:
            print("❌ PR_NUMBER not set")
            exit(1)

        print(f"Destroying droplet for PR #{pr_number}", flush=True)

        token = os.environ.get("DIGITALOCEAN_TOKEN")
        if not token:
            print("❌ DIGITALOCEAN_TOKEN not set")
            exit(1)

        droplet = HobbyTester.find_existing_droplet_for_pr(token=token, pr_number=pr_number)
        if not droplet:
            print(f"No droplet found for PR #{pr_number}")
            exit(0)

        print(f"Found droplet: {droplet.name} (ID: {droplet.id})")

        try:
            record_id = HobbyTester.find_dns_record_for_ip(token, droplet.ip_address)
            HobbyTester.destroy_environment(droplet_id=droplet.id, record_id=record_id)
            print(f"✅ Destroyed droplet for PR #{pr_number}")
        except Exception as e:
            print(f"❌ Failed to destroy: {e}")
            exit(1)


if __name__ == "__main__":
    main()
