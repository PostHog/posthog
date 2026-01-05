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
import digitalocean

DOMAIN = os.getenv("HOBBY_DOMAIN", "posthog.cc")


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
            'echo "$LOG_PREFIX Cloning PostHog repository"',
            "git clone https://github.com/PostHog/posthog.git",
            "cd posthog",
            f'echo "$LOG_PREFIX Fetching commit: {safe_sha}"',
            f"git fetch origin {safe_sha}",
            f'echo "$LOG_PREFIX Checking out commit: {safe_sha}"',
            f"git checkout {safe_sha}",
            "CURRENT_COMMIT=$(git rev-parse HEAD)",
            'echo "$LOG_PREFIX Current commit: $CURRENT_COMMIT"',
            "cd ..",
            'echo "$LOG_PREFIX Waiting for docker image to be available on DockerHub..."',
            self._get_wait_for_image_script(),
            "chmod +x posthog/bin/deploy-hobby",
            'echo "$LOG_PREFIX Starting deployment script"',
            "export SKIP_HEALTH_CHECK=1",
            f"./posthog/bin/deploy-hobby $CURRENT_COMMIT {safe_hostname} 1",
            "DEPLOY_EXIT=$?",
            'echo "$LOG_PREFIX Deployment script exited with code: $DEPLOY_EXIT"',
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

    def block_until_droplet_is_started(self):
        if not self.droplet:
            return
        actions = self.droplet.get_actions()
        up = False
        while not up:
            for action in actions:
                action.load()
                if action.status == "completed":
                    up = True
                    print(action.status)
                else:
                    print("Droplet not booted yet - waiting a bit", flush=True)
                    time.sleep(5)

    def get_public_ip(self):
        if not self.droplet:
            return
        ip = None
        while not ip:
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

        self.droplet = digitalocean.Droplet(
            token=self.token,
            name=self.name,
            region=self.region,
            image=self.image,
            size_slug=self.size,
            user_data=self.user_data,
            ssh_keys=keys,
            tags=tags,
        )
        self.droplet.create()
        return self.droplet

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

        # Update .env file with new image tag
        update_env_cmd = (
            f"cd /hobby && sed -i 's/^POSTHOG_APP_TAG=.*/POSTHOG_APP_TAG={new_sha}/' .env && grep POSTHOG_APP_TAG .env"
        )
        result = self.run_ssh_command(update_env_cmd, timeout=30)
        if result["exit_code"] != 0:
            raise RuntimeError(f"Failed to update .env: {result['stderr']}")
        print(f"✅ Updated POSTHOG_APP_TAG to {new_sha}")

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

    def test_deployment(self, timeout=45, retry_interval=15, stability_period=300):
        if not self.hostname:
            return
        # timeout in minutes, stability_period in seconds
        # return true if success or false if failure
        print("Attempting to reach the instance", flush=True)
        print(f"We will time out after {timeout} minutes", flush=True)
        print(f"Containers must be stable for {stability_period}s before success", flush=True)

        # Suppress SSL warnings for staging Let's Encrypt certificates
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        start_time = datetime.datetime.now()
        attempt = 1
        last_error = None
        http_502_count = 0
        connection_error_count = 0

        last_log_fetch = 0
        containers_healthy_since = None  # Track when containers first became healthy
        cloud_init_finished = False

        while datetime.datetime.now() < start_time + datetime.timedelta(minutes=timeout):
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            if attempt % 10 == 0:
                print(f"⏱️  Still trying... (attempt {attempt}, elapsed {int(elapsed)}s)", flush=True)
            print(f"Trying to connect... (attempt {attempt})", flush=True)

            health_check_passed = False
            try:
                # Using HTTP directly to avoid DNS/TLS complexity in CI
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

            # Periodic checks (every 60 seconds) - runs regardless of connection/HTTP status
            # Also check cloud-init status to fail fast if deployment failed
            if int(elapsed) - last_log_fetch > 60:
                if not cloud_init_finished:
                    finished, success, status = self.check_cloud_init_status()
                    if finished and not success:
                        # Cloud-init failed - stop immediately
                        print("\n❌ Cloud-init deployment FAILED", flush=True)
                        if status:
                            print(f"   Status: {status.get('status')}", flush=True)
                            errors = status.get("errors", [])
                            if errors:
                                print(f"   Errors: {errors}", flush=True)

                        print("\n📋 Cloud-init failure logs:", flush=True)
                        logs = self.fetch_cloud_init_logs()
                        if logs:
                            for line in logs.strip().split("\n")[-50:]:
                                print(f"  {line}", flush=True)

                        print(f"\n📍 For debugging, SSH to: ssh root@{self.droplet.ip_address}", flush=True)
                        return False

                    if finished and success:
                        cloud_init_finished = True
                        print("\n📋 Cloud-init completed successfully", flush=True)

                        # Check container health now that deployment finished
                        print("\n🐳 Checking docker container status...", flush=True)
                        all_healthy, unhealthy_containers, all_containers = self.check_container_health()
                        if unhealthy_containers:
                            print(f"\n❌ {len(unhealthy_containers)} container(s) failing!", flush=True)
                            failing_names = [c.get("Service", "unknown") for c in unhealthy_containers]
                            self.fetch_and_print_failing_container_logs(failing_names)
                            return False

            # Check for success: health check passed AND containers stable for required period
            if health_check_passed and cloud_init_finished:
                # Containers already checked above, now track stability
                if containers_healthy_since is None:
                    containers_healthy_since = datetime.datetime.now()
                    print(f"  ✅ All containers running, starting stability timer", flush=True)
                else:
                    stable_for = (datetime.datetime.now() - containers_healthy_since).total_seconds()
                    if stable_for >= stability_period:
                        elapsed_total = (datetime.datetime.now() - start_time).total_seconds()
                        print(
                            f"✅ Success - health check passed and containers stable for {int(stable_for)}s", flush=True
                        )
                        print(f"   Total time: {int(elapsed_total)}s", flush=True)
                        return True
                    else:
                        print(
                            f"  Health check passed, containers stable for {int(stable_for)}s / {stability_period}s",
                            flush=True,
                        )
            elif health_check_passed:
                print(f"  Health check passed but cloud-init not yet complete", flush=True)
            elif cloud_init_finished:
                # Cloud-init done but health check not passing - check if containers are healthy
                all_healthy, _, _ = self.check_container_health()
                if not all_healthy:
                    containers_healthy_since = None  # Reset if containers unhealthy

            time.sleep(retry_interval)
            attempt += 1

        # Health check failed - try to gather diagnostic info
        print("\nFailure - we timed out before receiving a heartbeat", flush=True)
        print("\n📋 Attempting to gather diagnostic information...", flush=True)

        droplet_info = self.get_droplet_info()
        if droplet_info:
            print(f"\n🖥️  Droplet Status:", flush=True)
            for key, value in droplet_info.items():
                print(f"  {key}: {value}", flush=True)

        kernel_logs = self.get_droplet_kernel_logs()
        if kernel_logs:
            print(f"\n📝 Kernel/Console Output (last 500 chars):", flush=True)
            print(kernel_logs[-500:] if len(kernel_logs) > 500 else kernel_logs, flush=True)

        # Fetch and show cloud-init logs via SSH
        print(f"\n📄 Cloud-init deployment logs:", flush=True)
        cloud_init_logs = self.fetch_cloud_init_logs()
        if cloud_init_logs:
            # Show last 50 lines
            log_lines = cloud_init_logs.strip().split("\n")[-50:]
            for line in log_lines:
                print(f"  {line}", flush=True)

            # Also write full logs to artifact for inspection
            artifact_path = "/tmp/cloud-init-output.log"
            with open(artifact_path, "w") as f:
                f.write(cloud_init_logs)
            print(f"  (Full logs saved to {artifact_path})", flush=True)
        else:
            print("  ❌ Could not fetch cloud-init logs via SSH", flush=True)

        # Check container health and fetch logs for failing containers
        print(f"\n🐳 Checking container health...", flush=True)
        all_healthy, unhealthy_containers, all_containers = self.check_container_health()
        if unhealthy_containers:
            print(f"\n❌ {len(unhealthy_containers)} container(s) failing!", flush=True)
            failing_names = [c.get("Service", "unknown") for c in unhealthy_containers]
            self.fetch_and_print_failing_container_logs(failing_names)

        # Provide diagnostic summary
        print(f"\n🔍 Failure Pattern Analysis:", flush=True)
        print(f"  - Connection errors: {connection_error_count}", flush=True)
        print(f"  - HTTP 502 (bad gateway): {http_502_count}", flush=True)
        print(f"  - Last error: {last_error}", flush=True)

        if http_502_count > 0:
            print("  💡 502 errors suggest nginx/caddy is up but the app isn't responding", flush=True)
            print("     Check cloud-init logs for deployment failures", flush=True)
        if connection_error_count > 0 and http_502_count == 0:
            print("  💡 Connection errors suggest the web service never started", flush=True)
            print("     Check if Docker containers are running", flush=True)

        print(
            f"\n📍 For manual debugging, SSH to: ssh root@{self.droplet.ip_address if self.droplet else '?'}",
            flush=True,
        )
        print(f"    Then check: tail -f /var/log/cloud-init-output.log", flush=True)
        print(f"    And: docker-compose logs", flush=True)

        return False

    def test_deployment_with_details(self, timeout=45, retry_interval=15, stability_period=300):
        """Like test_deployment but returns (success, failure_details) tuple."""
        if not self.hostname:
            return (False, {"reason": "no_hostname", "message": "No hostname configured"})

        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        start_time = datetime.datetime.now()
        attempt = 1
        last_error = None
        http_502_count = 0
        connection_error_count = 0
        last_log_fetch = 0
        containers_healthy_since = None
        cloud_init_finished = False
        failure_details: dict = {}

        while datetime.datetime.now() < start_time + datetime.timedelta(minutes=timeout):
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            if attempt % 10 == 0:
                print(f"⏱️  Still trying... (attempt {attempt}, elapsed {int(elapsed)}s)", flush=True)
            print(f"Trying to connect... (attempt {attempt})", flush=True)

            health_check_passed = False
            all_healthy = False
            try:
                # Using HTTP directly to avoid DNS/TLS complexity in CI
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
                if not cloud_init_finished:
                    finished, success, status = self.check_cloud_init_status()
                    if finished and not success:
                        print("\n❌ Cloud-init deployment FAILED", flush=True)
                        failure_details = {
                            "reason": "cloud_init_failed",
                            "message": "Cloud-init deployment failed",
                            "status": status.get("status") if status else None,
                            "errors": status.get("errors") if status else None,
                        }
                        return (False, failure_details)

                    if finished and success:
                        cloud_init_finished = True
                        print("\n📋 Cloud-init completed successfully", flush=True)

                if cloud_init_finished:
                    print("\n🐳 Container status:", flush=True)
                    _, stopped, containers = self.check_container_health()
                    if containers:
                        running_count = len(containers) - len(stopped)
                        print(f"  Running: {running_count}/{len(containers)} containers", flush=True)

                if not cloud_init_finished:
                    print("\n📋 Cloud-init progress:", flush=True)
                    logs = self.fetch_cloud_init_logs()
                    if logs:
                        for line in logs.strip().split("\n")[-10:]:
                            print(f"  {line}", flush=True)

                last_log_fetch = int(elapsed)
                print()

            if cloud_init_finished:
                all_healthy, stopped, containers = self.check_container_health()
                if not all_healthy and stopped:
                    print(f"\n❌ Container health check failed - failing fast", flush=True)
                    unhealthy_list = []
                    failing_names = []
                    for c in stopped:
                        container_info = f"{c.get('Service')}: {c.get('State')}"
                        unhealthy_list.append(container_info)
                        failing_names.append(c.get("Service", "unknown"))
                        print(f"    ❌ {container_info}", flush=True)

                    # Fetch logs from failing containers
                    self.fetch_and_print_failing_container_logs(failing_names)

                    # Also fetch kafka-init logs to debug topic creation issues
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

                    # Check for OOM kills in dmesg
                    print(f"\n📋 Checking for OOM kills:", flush=True)
                    oom_result = self.run_ssh_command(
                        "dmesg | grep -i 'oom\\|killed process' | tail -10 || true", timeout=15
                    )
                    if oom_result["exit_code"] == 0 and oom_result["stdout"].strip():
                        for line in oom_result["stdout"].strip().split("\n"):
                            print(f"    {line}", flush=True)
                    else:
                        print(f"    No OOM kills found", flush=True)

                    # Check memory usage
                    print(f"\n📋 Memory usage:", flush=True)
                    mem_result = self.run_ssh_command("free -h", timeout=15)
                    if mem_result["exit_code"] == 0 and mem_result["stdout"]:
                        for line in mem_result["stdout"].strip().split("\n"):
                            print(f"    {line}", flush=True)

                    print(f"\n📍 For debugging, SSH to: ssh root@{self.droplet.ip_address}", flush=True)
                    failure_details = {
                        "reason": "container_unhealthy",
                        "message": "Container health check failed",
                        "unhealthy_containers": unhealthy_list,
                    }
                    return (False, failure_details)

            if health_check_passed and cloud_init_finished:
                if containers_healthy_since is None:
                    containers_healthy_since = datetime.datetime.now()
                    print(f"  ✅ All containers running, starting stability timer", flush=True)
                else:
                    stable_for = (datetime.datetime.now() - containers_healthy_since).total_seconds()
                    if stable_for >= stability_period:
                        elapsed_total = (datetime.datetime.now() - start_time).total_seconds()
                        print(
                            f"✅ Success - health check passed and containers stable for {int(stable_for)}s",
                            flush=True,
                        )
                        print(f"   Total time: {int(elapsed_total)}s", flush=True)
                        return (True, {})
                    else:
                        print(
                            f"  Health check passed, containers stable for {int(stable_for)}s / {stability_period}s",
                            flush=True,
                        )
            elif health_check_passed:
                print(f"  Health check passed but cloud-init not yet complete", flush=True)
            elif cloud_init_finished and not all_healthy:
                containers_healthy_since = None

            time.sleep(retry_interval)
            attempt += 1

        print("\nFailure - we timed out before receiving a heartbeat", flush=True)
        failure_details = {
            "reason": "timeout",
            "message": f"Timed out after {timeout} minutes",
            "connection_errors": connection_error_count,
            "http_502_count": http_502_count,
            "last_error": last_error,
        }
        return (False, failure_details)

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
                "cd hobby && sudo -E docker-compose -f docker-compose.yml logs --tail=500 --no-log-prefix", timeout=60
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

        print("Waiting for deployment to become healthy", flush=True)
        print(f"Record ID: {record_id}", flush=True)
        print(f"Droplet ID: {droplet_id}", flush=True)

        ht = HobbyTester(
            name=name,
            record_id=record_id,
            droplet_id=droplet_id,
        )
        health_success, failure_details = ht.test_deployment_with_details()

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

    if command == "generate-demo-data":
        print("Generating demo data on droplet", flush=True)
        droplet_id = os.environ.get("HOBBY_DROPLET_ID")

        ht = HobbyTester(droplet_id=droplet_id)
        success = ht.generate_demo_data()
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
