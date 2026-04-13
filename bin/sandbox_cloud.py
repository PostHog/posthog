"""Cloud sandbox management — EC2 instances with Tailscale networking."""

from __future__ import annotations

import os
import sys
import gzip
import json
import time
import base64
import shutil
import subprocess
from pathlib import Path

from _sandbox_lib import (
    BUILD_CACHE_TEMPLATE,
    CLOUD_CONFIG_FILE,
    CLOUD_INIT_TEMPLATE,
    PROVISION_HOST_SNIPPET,
    REGISTRY_DIR,
    error,
    fatal,
    info,
    run,
    slugify,
    success,
    warn,
)


def _render_template(template_path: Path, replacements: dict[str, str]) -> str:
    """Load a shell template and substitute placeholders.

    Always inlines __PROVISION_HOST__ first — that's the shared helper block
    sourced by both cloud-init.sh and build-cache.sh, and it must land before
    any other placeholder substitution so the helpers are defined as bash
    functions before the first call site.
    """
    text = template_path.read_text()
    text = text.replace("__PROVISION_HOST__", PROVISION_HOST_SNIPPET.read_text())
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    return text


# Host-side port mapping for the container's sshd. bin/sandbox computes this
# as `PORT_BASE + 2000`; on a cloud instance the registry is always fresh so
# PORT_BASE (48001) is always chosen → SSH_PORT = 50001. Hardcoded here rather
# than read back over SSH because it's a structural invariant of the cloud
# flow, not per-sandbox state.
CLOUD_CONTAINER_SSH_PORT = 50001

_JETBRAINS_CHOICES = ("pycharm", "intellij")


def _local_jetbrains_preference() -> str:
    """Read the user's local JetBrains preference from the local sandbox config.

    Returns "pycharm", "intellij", or "" (none / not configured). The cloud
    instance inherits whatever the user already picked locally, so there's no
    second prompt.
    """
    try:
        data = json.loads((REGISTRY_DIR / "config.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return ""
    val = data.get("jetbrains")
    return val if val in _JETBRAINS_CHOICES else ""


def _tailnet_url(hostname: str) -> str:
    """Return the best-effort browser URL for a cloud sandbox.

    Prefers the https FQDN (HTTP/2 via Tailscale Serve + Let's Encrypt) when
    we can read the tailnet MagicDNSSuffix from the local tailscale daemon.
    Falls back to plain http on the short hostname when the suffix isn't
    available or tailscale isn't reachable locally.
    """
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            suffix = (json.loads(result.stdout) or {}).get("MagicDNSSuffix", "")
            if suffix:
                return f"https://{hostname}.{suffix}"
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return f"http://{hostname}"


def _load_cloud_config() -> dict:
    try:
        return json.loads(CLOUD_CONFIG_FILE.read_text())
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        fatal(f"Corrupt cloud config {CLOUD_CONFIG_FILE}: {e}")


def _save_cloud_config(config: dict) -> None:
    CLOUD_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CLOUD_CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n")


_REQUIRED_CONFIG_KEYS = (
    "s3_bucket",
    "s3_key",
    "security_group_id",
    "subnet_id",
    "region",
    "aws_profile",
)


def _ensure_cloud_config() -> dict:
    config = _load_cloud_config()

    missing = [k for k in _REQUIRED_CONFIG_KEYS if k not in config]
    if not missing:
        return config

    if not sys.stdin.isatty():
        fatal(
            f"Cloud config {CLOUD_CONFIG_FILE} is missing keys: {', '.join(missing)}.\n"
            "  Run `sandbox cloud create` once interactively to set it up."
        )

    if "s3_bucket" in missing:
        config["s3_bucket"] = (
            input("S3 bucket for Docker cache [posthog-sandbox-cache]: ").strip() or "posthog-sandbox-cache"
        )
    if "s3_key" in missing:
        config["s3_key"] = (
            input("S3 key for Docker cache archive [docker-data.tar.zst]: ").strip() or "docker-data.tar.zst"
        )
    if "security_group_id" in missing:
        val = input("Security group ID: ").strip()
        if not val:
            fatal("Security group ID is required.")
        config["security_group_id"] = val
    if "subnet_id" in missing:
        val = input("Subnet ID (with internet access): ").strip()
        if not val:
            fatal("Subnet ID is required.")
        config["subnet_id"] = val
    if "region" in missing:
        config["region"] = input("AWS region [us-east-1]: ").strip() or "us-east-1"
    if "aws_profile" in missing:
        config["aws_profile"] = input("AWS CLI profile name [default]: ").strip() or "default"

    _save_cloud_config(config)
    return config


def _cloud_hostname(owner: str, branch: str) -> str:
    """Random suffix prevents collisions with stale Tailscale nodes."""
    import secrets

    slug = slugify(branch)
    suffix = secrets.token_hex(3)
    hostname = f"sandbox-{owner}-{slug}-{suffix}"
    # Tailscale hostnames max 63 chars, must not end with '-'
    if len(hostname) > 63:
        hostname = hostname[:63].rstrip("-")
    return hostname


def _aws(config: dict, *args: str, capture: bool = True) -> subprocess.CompletedProcess:
    cmd = [
        "aws",
        "--region",
        config["region"],
        "--profile",
        config["aws_profile"],
        "--output",
        "json",
        *args,
    ]
    try:
        return subprocess.run(cmd, check=True, capture_output=capture, text=capture)
    except FileNotFoundError:
        fatal(
            "AWS CLI not found. Install it: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
        )
    except subprocess.CalledProcessError as e:
        error(f"aws {' '.join(args)} failed (exit {e.returncode})")
        for line in (e.stderr or "").strip().splitlines():
            print(f"  {line}", file=sys.stderr)
        sys.exit(1)


def _cloud_get_owner() -> str:
    result = run(["git", "config", "user.email"], capture=True, check=False)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().split("@")[0].replace(".", "-")
    return os.environ.get("USER", "unknown")


def _cloud_find_instance(config: dict, branch: str) -> dict | None:
    owner = _cloud_get_owner()
    result = _aws(
        config,
        "ec2",
        "describe-instances",
        "--filters",
        f"Name=tag:sandbox:owner,Values={owner}",
        f"Name=tag:sandbox:branch,Values={branch}",
        "Name=instance-state-name,Values=running,stopped,pending,stopping",
    )
    data = json.loads(result.stdout)
    for reservation in data.get("Reservations", []):
        for instance in reservation.get("Instances", []):
            return instance
    return None


def _cloud_list_instances(config: dict) -> list[dict]:
    owner = _cloud_get_owner()
    result = _aws(
        config,
        "ec2",
        "describe-instances",
        "--filters",
        f"Name=tag:sandbox:owner,Values={owner}",
        "Name=tag:sandbox,Values=true",
        "Name=instance-state-name,Values=running,stopped,pending,stopping",
    )
    data = json.loads(result.stdout)
    instances = []
    for reservation in data.get("Reservations", []):
        instances.extend(reservation.get("Instances", []))
    return instances


def _cloud_get_tag(instance: dict, key: str) -> str:
    for tag in instance.get("Tags", []):
        if tag["Key"] == key:
            return tag["Value"]
    return ""


def _require_instance(branch: str, *, require_running: bool = True) -> tuple[dict, dict, str]:
    config = _ensure_cloud_config()
    instance = _cloud_find_instance(config, branch)
    if not instance:
        fatal(f"No cloud sandbox found for branch '{branch}'")
    if require_running and instance["State"]["Name"] != "running":
        fatal(f"Sandbox is not running (state: {instance['State']['Name']})")
    hostname = _cloud_get_tag(instance, "sandbox:hostname")
    if require_running and not hostname:
        fatal("No Tailscale hostname found for this sandbox")
    return config, instance, hostname


def _ssh_cmd(
    hostname: str,
    *,
    user: str = "ubuntu",
    port: int | None = None,
    agent_forward: bool = False,
    tty: bool = False,
    connect_timeout: int | None = None,
) -> list[str]:
    cmd = ["ssh"]
    if agent_forward:
        cmd.append("-A")
    if tty:
        cmd.append("-t")
    cmd.extend(
        [
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
        ]
    )
    if port is not None:
        cmd.extend(["-p", str(port)])
    if connect_timeout is not None:
        cmd.extend(["-o", f"ConnectTimeout={connect_timeout}"])
    cmd.append(f"{user}@{hostname}")
    return cmd


def _container_ssh_cmd(
    hostname: str,
    *,
    agent_forward: bool = False,
    tty: bool = False,
    connect_timeout: int | None = None,
) -> list[str]:
    """SSH command targeting the container's sshd (port 50001, user sandbox).

    Unlike _ssh_cmd which reaches the EC2 host, this connects directly to the
    container's sshd through Docker's port mapping. This is essential for SSH
    agent forwarding — the agent socket is carried into the container process
    rather than being stranded on the EC2 host.
    """
    return _ssh_cmd(
        hostname,
        user="sandbox",
        port=CLOUD_CONTAINER_SSH_PORT,
        agent_forward=agent_forward,
        tty=tty,
        connect_timeout=connect_timeout,
    )


def _cloud_render_user_data(
    branch: str,
    owner: str,
    hostname: str,
    tailscale_key: str,
    ssh_keys: str,
    claude_credentials: str,
    claude_settings: str,
    claude_json: str,
    s3_archive_manifest: str,
    jetbrains: str,
) -> str:
    """Returns base64-encoded gzip data for AWS user-data."""

    def b64(val: str) -> str:
        return base64.b64encode(val.encode()).decode() if val else ""

    rendered = _render_template(
        CLOUD_INIT_TEMPLATE,
        {
            "__SANDBOX_BRANCH__": branch,
            "__SANDBOX_OWNER__": owner,
            "__SANDBOX_HOSTNAME__": hostname,
            "__SANDBOX_JETBRAINS__": jetbrains,
            "__TAILSCALE_AUTH_KEY_B64__": b64(tailscale_key),
            "__SSH_AUTHORIZED_KEYS_B64__": b64(ssh_keys),
            "__CLAUDE_CREDENTIALS_B64__": b64(claude_credentials),
            "__CLAUDE_SETTINGS_B64__": b64(claude_settings),
            "__CLAUDE_JSON_B64__": b64(claude_json),
            "__S3_ARCHIVE_MANIFEST_B64__": b64(s3_archive_manifest),
        },
    )

    compressed = gzip.compress(rendered.encode(), compresslevel=9)
    return base64.b64encode(compressed).decode()


def _cloud_get_tailscale_key(config: dict) -> str:
    if "tailscale_auth_key" in config:
        return config["tailscale_auth_key"]

    secret_arn = config.get("tailscale_secret_arn")
    if secret_arn:
        result = _aws(config, "secretsmanager", "get-secret-value", "--secret-id", secret_arn)
        data = json.loads(result.stdout)
        return data["SecretString"]

    key = input("Tailscale auth key (reusable + ephemeral): ").strip()
    if not key:
        fatal(
            "Tailscale auth key is required.\n  Generate a reusable + ephemeral key at https://login.tailscale.com/admin/settings/keys\n  (Ephemeral ensures nodes auto-remove when instances terminate.)"
        )
    config["tailscale_auth_key"] = key
    _save_cloud_config(config)
    return key


def _cloud_gather_auth() -> tuple[str, str, str, str]:
    ssh_dir = Path.home() / ".ssh"
    ssh_keys = [pub.read_text().strip() for pub in ssh_dir.glob("*.pub")] if ssh_dir.is_dir() else []

    if not ssh_keys:
        fatal(
            "No SSH public keys found in ~/.ssh/.\n"
            "  You need at least one SSH key to connect to the sandbox.\n"
            "  Generate one with: ssh-keygen -t ed25519"
        )

    claude_dir = Path.home() / ".claude"
    claude_credentials = ""
    claude_settings = ""
    claude_json = ""

    creds_file = claude_dir / ".credentials.json"
    if creds_file.exists():
        claude_credentials = creds_file.read_text().strip()
    elif sys.platform == "darwin":
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            claude_credentials = result.stdout.strip()

    if not claude_credentials:
        warn("No Claude Code credentials found. Claude Code won't work on the sandbox until you log in manually.")

    settings_file = claude_dir / "settings.json"
    if settings_file.exists():
        claude_settings = settings_file.read_text().strip()

    claude_json_file = Path.home() / ".claude.json"
    if claude_json_file.exists():
        # Only include auth-relevant fields — the full file can exceed
        # the 16KB AWS user-data limit (projects history is ~10KB alone).
        CLAUDE_JSON_KEEP = {"oauthAccount", "userID", "hasCompletedOnboarding"}
        full = json.loads(claude_json_file.read_text())
        claude_json = json.dumps({k: v for k, v in full.items() if k in CLAUDE_JSON_KEEP})

    return "\n".join(ssh_keys), claude_credentials, claude_settings, claude_json


def _cloud_discover_ubuntu_ami(config: dict) -> str:
    info("Discovering latest Ubuntu 24.04 AMI...")
    result = _aws(
        config,
        "ec2",
        "describe-images",
        "--owners",
        "099720109477",
        "--filters",
        "Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*",
        "Name=state,Values=available",
        "--query",
        "sort_by(Images, &CreationDate)[-1].ImageId",
        "--output",
        "text",
    )
    ami_id = result.stdout.strip()
    if not ami_id or ami_id == "None":
        fatal("Could not find Ubuntu 24.04 AMI. Check your AWS region and credentials.")
    info(f"  Using AMI: {ami_id}")
    return ami_id


def _cloud_generate_presigned_urls(config: dict) -> str:
    """Download the cache manifest from S3 and pre-sign each chunk URL.

    Returns a JSON string: [{"name": "base.tar.zst", "url": "https://..."}, ...]
    """
    bucket = config["s3_bucket"]
    key = config["s3_key"]
    prefix = key.replace(".tar.zst", "")
    manifest_uri = f"s3://{bucket}/{prefix}/manifest.json"

    # Download manifest (bypass _aws() so we can handle "not found" without fataling)
    result = subprocess.run(
        ["aws", "--region", config["region"], "--profile", config["aws_profile"], "s3", "cp", manifest_uri, "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        fatal(
            f"Cache manifest not found at {manifest_uri}\n"
            "  Build the cache first: bin/sandbox cloud build-cache\n"
            "  Or upload from local:  bin/sandbox cloud upload-cache"
        )
    manifest = json.loads(result.stdout)

    chunks = manifest.get("chunks", [])
    if not chunks:
        fatal(f"Cache manifest at {manifest_uri} has no chunks listed")

    info(f"Generating pre-signed URLs for {len(chunks)} cache chunks...")
    urls = []
    for chunk_name in chunks:
        chunk_uri = f"s3://{bucket}/{prefix}/{chunk_name}"
        result = _aws(config, "s3", "presign", chunk_uri, "--expires-in", "3600")
        url = result.stdout.strip()
        if not url:
            fatal(f"Failed to generate pre-signed URL for {chunk_uri}")
        urls.append({"name": chunk_name, "url": url})

    return json.dumps(urls)


def _abort_if_instance_exists(config: dict, branch: str) -> None:
    """Error out if a sandbox for *branch* already exists (any state)."""
    existing = _cloud_find_instance(config, branch)
    if not existing:
        return
    state = existing["State"]["Name"]
    instance_id = existing["InstanceId"]
    error(f"Sandbox for '{branch}' already exists ({instance_id}, state: {state})")
    if state == "running":
        print(f"  Connect:    sandbox cloud shell {branch}")
    print(f"  Destroy it: sandbox cloud destroy {branch}")
    sys.exit(1)


def _negotiate_branch_ref(branch: str) -> None:
    """If local has commits not pushed to origin, offer to push them.

    The cloud instance checks out `branch` from origin during cloud-init, so
    local-only work won't be visible otherwise.
    """
    remote_ref = run(["git", "ls-remote", "--heads", "origin", branch], capture=True, check=False).stdout.strip()
    local_ref = run(["git", "rev-parse", "--verify", f"refs/heads/{branch}"], capture=True, check=False).stdout.strip()

    if local_ref and not remote_ref:
        warn(f"Branch '{branch}' exists locally but not on the remote.")
        answer = input("  Push to origin before creating sandbox? [Y/n] ").strip().lower()
        if answer in ("", "y", "yes"):
            run(["git", "push", "-u", "origin", branch], check=True)
        else:
            info("Continuing — sandbox will start from master.")
    elif local_ref and remote_ref:
        remote_sha = remote_ref.split()[0]
        if local_ref != remote_sha:
            warn(f"Local '{branch}' ({local_ref[:8]}) differs from remote ({remote_sha[:8]}).")
            answer = input("  Push local to origin before creating sandbox? [Y/n] ").strip().lower()
            if answer in ("", "y", "yes"):
                run(["git", "push", "origin", branch], check=True)


def _launch_instance(config: dict, branch: str, owner: str, hostname: str) -> str:
    """Render user-data, call ec2 run-instances, wait for instance-running, return instance id."""
    ami_id = _cloud_discover_ubuntu_ami(config)
    s3_archive_manifest = _cloud_generate_presigned_urls(config)
    tailscale_key = _cloud_get_tailscale_key(config)
    ssh_keys, claude_credentials, claude_settings, claude_json = _cloud_gather_auth()
    jetbrains = _local_jetbrains_preference()
    if jetbrains:
        info(f"  JetBrains IDE: {jetbrains} (inherited from local config)")

    user_data = _cloud_render_user_data(
        branch=branch,
        owner=owner,
        hostname=hostname,
        tailscale_key=tailscale_key,
        ssh_keys=ssh_keys,
        claude_credentials=claude_credentials,
        claude_settings=claude_settings,
        claude_json=claude_json,
        s3_archive_manifest=s3_archive_manifest,
        jetbrains=jetbrains,
    )

    user_data_bytes = len(base64.b64decode(user_data))
    info(f"  User data size: {user_data_bytes} bytes (gzip compressed, limit 16384)")
    if user_data_bytes > 16384:
        fatal(
            f"User data is {user_data_bytes} bytes, exceeding AWS 16KB limit.\n"
            "  This usually means Claude settings or SSH keys are too large.\n"
            "  Check ~/.claude/settings.json and ~/.ssh/*.pub"
        )

    tags = json.dumps(
        [
            {
                "ResourceType": "instance",
                "Tags": [
                    {"Key": "Name", "Value": f"sandbox-{owner}-{slugify(branch)}"},
                    {"Key": "sandbox", "Value": "true"},
                    {"Key": "sandbox:owner", "Value": owner},
                    {"Key": "sandbox:branch", "Value": branch},
                    {"Key": "sandbox:hostname", "Value": hostname},
                    {"Key": "sandbox:created", "Value": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                ],
            }
        ]
    )

    result = _aws(
        config,
        "ec2",
        "run-instances",
        "--image-id",
        ami_id,
        "--instance-type",
        "m6id.2xlarge",
        "--subnet-id",
        config["subnet_id"],
        "--security-group-ids",
        config["security_group_id"],
        "--block-device-mappings",
        "DeviceName=/dev/sda1,Ebs={VolumeSize=100,VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}",
        "--metadata-options",
        "HttpTokens=required,HttpEndpoint=enabled,HttpPutResponseHopLimit=2",
        "--user-data",
        user_data,
        "--tag-specifications",
        tags,
    )

    instance_id = json.loads(result.stdout)["Instances"][0]["InstanceId"]
    info(f"  Instance: {instance_id}")

    info("Waiting for instance to start...")
    _aws(config, "ec2", "wait", "instance-running", "--instance-ids", instance_id)
    return instance_id


def _wait_for_tailscale_ssh(hostname: str, instance_id: str, *, timeout: int = 180) -> None:
    """Poll `ssh true` until it succeeds or *timeout* seconds elapse."""
    ssh_base = _ssh_cmd(hostname, connect_timeout=5)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if run(ssh_base + ["true"], check=False, capture=True).returncode == 0:
            return
        time.sleep(5)
    fatal(
        f"Timed out waiting for Tailscale SSH on {hostname}.\n"
        f"  Instance: {instance_id}\n"
        f"  Try manually: ssh ubuntu@{hostname}"
    )


def _tail_boot_log_until_done(hostname: str, branch: str) -> bool:
    """Stream /var/log/sandbox-boot.log until the sandbox is ready to attach.

    Returns True when the container is running and tmux/Claude are live
    (the app may still be booting). Returns False if the user Ctrl-C'd.
    Fatals if the stream ends without the marker (cloud-init crashed).
    """
    ssh_base = _ssh_cmd(hostname, connect_timeout=5)
    proc: subprocess.Popen | None = None
    try:
        proc = subprocess.Popen(
            ssh_base + ["tail -n +1 -f /var/log/sandbox-boot.log"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="")
            if "Cloud sandbox ready" in line:
                proc.terminate()
                proc.wait()
                return True
    except KeyboardInterrupt:
        if proc is not None:
            proc.terminate()
            proc.wait()
        info("\nDetached from boot log. Sandbox is still booting.")
        print(f"  Reattach:  sandbox cloud logs {branch}")
        print(f"  Shell:     sandbox cloud shell {branch}")
        return False

    fatal(f"Boot log ended without ready marker.\n  Check logs: sandbox cloud logs {branch}")


def _open_browser_detached(url: str) -> None:
    """Pop a browser to *url* without blocking the parent process."""
    subprocess.Popen(
        [sys.executable, "-c", f"import webbrowser; webbrowser.open({url!r})"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def cmd_cloud_create(branch: str) -> None:
    config = _ensure_cloud_config()
    owner = _cloud_get_owner()
    hostname = _cloud_hostname(owner, branch)

    _abort_if_instance_exists(config, branch)
    _negotiate_branch_ref(branch)

    info(f"Creating cloud sandbox for '{branch}'...")
    info(f"  Tailscale hostname: {hostname}")

    instance_id = _launch_instance(config, branch, owner, hostname)

    info(f"Instance {instance_id} running. Waiting for Tailscale SSH...")
    _wait_for_tailscale_ssh(hostname, instance_id)
    success(f"SSH connected to {hostname}")

    info("Tailing boot log (Ctrl-C to detach, sandbox keeps booting)...")
    print()
    if not _tail_boot_log_until_done(hostname, branch):
        return

    print()
    success(f"Cloud sandbox ready for '{branch}'")

    # Tailscale Serve terminates TLS at 443 (or plain HTTP at 80 as a
    # fallback) and proxies to the sandbox proxy on 48001, so the canonical
    # URL has no port.
    _open_browser_detached(_tailnet_url(hostname))

    info("Attaching to mprocs... (detach with Ctrl-b d)")
    ssh = _container_ssh_cmd(hostname, agent_forward=True, tty=True)
    os.execvp("ssh", ssh + ["tmux", "-L", "sandbox", "attach-session", "-t", "posthog:claude"])


def cmd_cloud_destroy(branch: str) -> None:
    config, instance, hostname = _require_instance(branch, require_running=False)
    instance_id = instance["InstanceId"]

    warn(f"Destroying cloud sandbox for '{branch}' (instance {instance_id})...")

    _aws(config, "ec2", "terminate-instances", "--instance-ids", instance_id)
    success("Instance terminating.")

    if hostname:
        info(f"Tailscale node '{hostname}' will auto-remove after ~30-60 min offline (ephemeral key).")


def cmd_cloud_list() -> None:
    config = _ensure_cloud_config()
    instances = _cloud_list_instances(config)

    if not instances:
        print("No cloud sandboxes found. Create one with: sandbox cloud create <branch>")
        return

    print(f"{'BRANCH':<40} {'STATE':<12} {'INSTANCE':<22} HOSTNAME")
    print(f"{'------':<40} {'-----':<12} {'--------':<22} --------")

    for inst in instances:
        branch = _cloud_get_tag(inst, "sandbox:branch")
        hostname = _cloud_get_tag(inst, "sandbox:hostname")
        state = inst["State"]["Name"]
        instance_id = inst["InstanceId"]
        print(f"{branch:<40} {state:<12} {instance_id:<22} {hostname}")


def cmd_cloud_shell(branch: str) -> None:
    _config, _instance, hostname = _require_instance(branch)
    # SSH directly into the container's sshd so the agent is forwarded all
    # the way in. Attach to the existing tmux session (same as local shell).
    ssh = _container_ssh_cmd(hostname, agent_forward=True, tty=True)
    os.execvp("ssh", ssh + ["tmux", "-L", "sandbox", "attach-session", "-t", "posthog:claude"])


def cmd_cloud_open(branch: str) -> None:
    import webbrowser

    _config, _instance, hostname = _require_instance(branch)
    url = _tailnet_url(hostname)
    info(f"Opening {url}...")
    webbrowser.open(url)


def cmd_cloud_logs(branch: str) -> None:
    _config, _instance, hostname = _require_instance(branch)

    slug = slugify(branch)
    container = f"sandbox-{slug}-app-1"

    ssh = _ssh_cmd(hostname, tty=True)
    os.execvp(
        "ssh",
        ssh
        + [
            f"echo '=== Boot log ===' && cat /var/log/sandbox-boot.log 2>/dev/null; "
            f"echo '\\n=== App container logs ===' && docker logs -f {container}",
        ],
    )


def cmd_cloud_code(branch: str) -> None:
    _config, _instance, hostname = _require_instance(branch)

    code_cmd = shutil.which("code")
    if not code_cmd:
        info("VSCode 'code' CLI not found on PATH.")
        info(f"Connect manually: code --remote ssh-remote+sandbox@{hostname}:{CLOUD_CONTAINER_SSH_PORT} /workspace")
        return

    info(f"Opening VSCode Remote-SSH to {hostname}:{CLOUD_CONTAINER_SSH_PORT}...")
    subprocess.Popen([code_cmd, "--remote", f"ssh-remote+sandbox@{hostname}:{CLOUD_CONTAINER_SSH_PORT}", "/workspace"])


def cmd_cloud_idea(branch: str) -> None:
    _config, _instance, hostname = _require_instance(branch)

    if not _local_jetbrains_preference():
        fatal(
            "No JetBrains IDE configured.\n"
            "  The cloud sandbox inherits the preference from the local sandbox config.\n"
            "  Either:\n"
            "    1. Run `sandbox create <any-branch>` once and pick PyCharm or IntelliJ, then\n"
            "       recreate the cloud sandbox: `sandbox cloud destroy ... && sandbox cloud create ...`\n"
            "    2. Or edit ~/.posthog-sandboxes/config.json and set\n"
            '       "jetbrains": "pycharm" (or "intellij"), then recreate.'
        )

    from urllib.parse import quote

    # Gateway SSHes straight through Tailscale → Docker port forwarding → the
    # container's sshd. One hop, no EC2-host-side bastion. See
    # infra/cloud-sandbox/HANDOFF.md for the topology diagram.
    uri = (
        f"jetbrains-gateway://connect#type=ssh&deploy=false"
        f"&host={hostname}&port={CLOUD_CONTAINER_SSH_PORT}&user=sandbox"
        f"&projectPath={quote('/workspace')}"
        f"&idePath={quote('/opt/idea')}"
    )

    for cmd_name in ["gateway", "jetbrains-gateway", "xdg-open", "open"]:
        cmd = shutil.which(cmd_name)
        if cmd:
            info(f"Opening JetBrains Gateway for sandbox at {hostname}...")
            subprocess.Popen([cmd, uri])
            return

    info("Could not auto-open Gateway.")
    info(f"Connect manually: File -> Remote Development -> SSH")
    info(f"  Host: {hostname}  Port: {CLOUD_CONTAINER_SSH_PORT}  User: sandbox")
    info(f"  Project: /workspace")


def _ensure_jetbrains_in_cache() -> None:
    """Install both JetBrains IDEs into Docker volumes for inclusion in cache."""
    products = [
        ("intellij", "IIU", "IntelliJ IDEA Ultimate"),
        ("pycharm", "PCP", "PyCharm Professional"),
    ]
    for product, code, name in products:
        volume = f"sandbox-{product}"
        run(["docker", "volume", "create", volume], capture=True, check=False)
        result = run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{volume}:/opt/idea",
                "alpine",
                "sh",
                "-c",
                "test -x /opt/idea/bin/remote-dev-server.sh && echo yes",
            ],
            capture=True,
            check=False,
        )
        if result.stdout.strip() == "yes":
            info(f"  {name} already in cache")
            continue

        info(f"  Downloading {name}...")
        api_url = f"https://data.services.jetbrains.com/products/releases?code={code}&latest=true&type=release"
        result = run(["curl", "-sfL", api_url], capture=True)
        download_url = json.loads(result.stdout)[code][0]["downloads"]["linux"]["link"]
        run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{volume}:/opt/idea",
                "-e",
                f"DL_URL={download_url}",
                "alpine",
                "sh",
                "-c",
                "apk add --no-cache curl > /dev/null 2>&1 && "
                'curl -fSL "$DL_URL" | tar -xzf - -C /opt/idea --strip-components=1',
            ]
        )
        info(f"  {name} installed into {volume}")


def cmd_cloud_upload_cache() -> None:
    config = _ensure_cloud_config()
    s3_key = config["s3_key"]
    s3_prefix = s3_key.replace(".tar.zst", "")

    info("Archiving Docker data for cloud sandbox cache...")

    result = run(["docker", "info", "--format", "{{.Images}}"], capture=True, check=False)
    if result.returncode != 0:
        fatal("Docker is not running. Start Docker first.")
    info(f"  Docker has {result.stdout.strip()} images")

    info("Ensuring JetBrains IDEs are in cache...")
    _ensure_jetbrains_in_cache()

    info("Stopping sandbox containers...")
    run(["docker", "compose", "-p", "sandbox-cache-init", "down", "-t", "0"], check=False, capture=True)

    archive_dir = Path("/tmp/docker-cache")
    if archive_dir.exists():
        shutil.rmtree(archive_dir)
    archive_dir.mkdir()

    num_chunks = 4
    # The shell script runs inside Alpine to access Docker Desktop's /var/lib/docker.
    # It creates split archives: base.tar.zst (everything except overlay2) plus
    # overlay2-{0..N}.tar.zst (overlay2 entries partitioned round-robin).
    split_script = (
        (
            "set -e && "
            "apk add --no-cache zstd > /dev/null 2>&1 && "
            "(cd /docker && ls -1 | grep -v '^overlay2$' | tar cf - -T -) | zstd -T0 -3 > /output/base.tar.zst & "
            "BASE_PID=$! ; "
            "OVERLAY_PIDS='' ; "
            "if [ -d /docker/overlay2 ]; then "
            "ls -1 /docker/overlay2 > /tmp/entries.txt; "
            "for i in $(seq 0 __LAST_CHUNK__); do "
            "awk -v c=$i -v n=__NUM_CHUNKS__ '(NR-1) % n == c {print \"overlay2/\" $0}' "
            "/tmp/entries.txt > /tmp/chunk-${i}.txt; "
            "tar cf - -C /docker -T /tmp/chunk-${i}.txt | zstd -T0 -3 > /output/overlay2-${i}.tar.zst & "
            'OVERLAY_PIDS="$OVERLAY_PIDS $!" ; '
            "done; fi; "
            "wait $BASE_PID || exit 1; "
            "for pid in $OVERLAY_PIDS; do wait $pid || exit 1; done"
        )
        .replace("__NUM_CHUNKS__", str(num_chunks))
        .replace("__LAST_CHUNK__", str(num_chunks - 1))
    )

    info("Creating split archives (this may take several minutes)...")
    run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            "/var/lib/docker:/docker:ro",
            "-v",
            "/tmp/docker-cache:/output",
            "alpine",
            "sh",
            "-c",
            split_script,
        ]
    )

    # Build manifest from the generated chunk files
    chunks = sorted(f for f in os.listdir(archive_dir) if f.endswith(".tar.zst"))
    manifest = {"version": 2, "chunks": chunks}
    (archive_dir / "manifest.json").write_text(json.dumps(manifest))

    total_size = sum((archive_dir / c).stat().st_size for c in chunks)
    info(f"  {len(chunks)} chunks, total {total_size / (1024 * 1024):.0f} MB")
    for c in chunks:
        info(f"    {c}: {(archive_dir / c).stat().st_size / (1024 * 1024):.0f} MB")

    s3_base = f"s3://{config['s3_bucket']}/{s3_prefix}"
    info(f"Uploading to {s3_base}/...")
    for f in os.listdir(archive_dir):
        _aws(config, "s3", "cp", str(archive_dir / f), f"{s3_base}/{f}", capture=False)

    shutil.rmtree(archive_dir, ignore_errors=True)

    success(f"Docker cache uploaded to {s3_base}/ ({total_size / (1024 * 1024):.0f} MB)")


def _cloud_export_credentials(config: dict) -> str:
    result = subprocess.run(
        ["aws", "configure", "export-credentials", "--profile", config["aws_profile"], "--format", "process"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        fatal(
            "Could not export AWS credentials. Make sure you're logged in:\n"
            f"  aws sso login --profile {config['aws_profile']}"
        )
    creds = json.loads(result.stdout)
    lines = [
        f'export AWS_ACCESS_KEY_ID="{creds["AccessKeyId"]}"',
        f'export AWS_SECRET_ACCESS_KEY="{creds["SecretAccessKey"]}"',
    ]
    if creds.get("SessionToken"):
        lines.append(f'export AWS_SESSION_TOKEN="{creds["SessionToken"]}"')
    return "\n".join(lines)


def cmd_cloud_build_cache() -> None:
    config = _ensure_cloud_config()
    ami_id = _cloud_discover_ubuntu_ami(config)

    info("Exporting AWS credentials for build instance...")
    aws_creds_env = _cloud_export_credentials(config)

    current_branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture=True).stdout.strip()
    if current_branch == "HEAD":
        current_branch = ""  # detached HEAD, use master

    rendered = _render_template(
        BUILD_CACHE_TEMPLATE,
        {
            "__AWS_CREDENTIALS_B64__": base64.b64encode(aws_creds_env.encode()).decode(),
            "__BUILD_BRANCH__": current_branch,
            "__S3_BUCKET__": config["s3_bucket"],
            "__S3_KEY__": config["s3_key"],
            "__AWS_REGION__": config["region"],
        },
    )
    user_data = base64.b64encode(rendered.encode()).decode()

    s3_prefix = config["s3_key"].replace(".tar.zst", "")
    info(f"Launching cache builder instance...")
    info(f"  S3 target: s3://{config['s3_bucket']}/{s3_prefix}/")

    result = _aws(
        config,
        "ec2",
        "run-instances",
        "--image-id",
        ami_id,
        "--instance-type",
        "m6id.2xlarge",
        "--subnet-id",
        config["subnet_id"],
        "--security-group-ids",
        config["security_group_id"],
        "--block-device-mappings",
        "DeviceName=/dev/sda1,Ebs={VolumeSize=40,VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}",
        "--metadata-options",
        "HttpTokens=required,HttpEndpoint=enabled,HttpPutResponseHopLimit=2",
        "--user-data",
        user_data,
        "--instance-initiated-shutdown-behavior",
        "stop",
        "--tag-specifications",
        json.dumps(
            [
                {
                    "ResourceType": "instance",
                    "Tags": [
                        {"Key": "Name", "Value": "sandbox-cache-builder"},
                        {"Key": "sandbox", "Value": "true"},
                        {"Key": "sandbox-cache-builder", "Value": "true"},
                    ],
                }
            ]
        ),
    )

    data = json.loads(result.stdout)
    instance_id = data["Instances"][0]["InstanceId"]
    info(f"  Instance: {instance_id}")
    info("Waiting for build to complete (instance stops itself when done)...")
    info("  This typically takes 15-20 minutes.")
    info(
        f"  SSH:  aws ec2-instance-connect ssh --instance-id {instance_id} "
        f"--connection-type eice --os-user ubuntu --profile {config['aws_profile']}"
    )
    info(f"  Logs: sudo tail -f /var/log/sandbox-build-cache.log")

    timeout = 3600
    elapsed = 0
    interval = 30
    s3_prefix = config["s3_key"].replace(".tar.zst", "")
    manifest_uri = f"s3://{config['s3_bucket']}/{s3_prefix}/manifest.json"
    while elapsed < timeout:
        state_result = _aws(
            config,
            "ec2",
            "describe-instances",
            "--instance-ids",
            instance_id,
            "--query",
            "Reservations[0].Instances[0].State.Name",
            "--output",
            "text",
        )
        state = state_result.stdout.strip()

        if state in ("stopped", "stopping", "terminated", "shutting-down"):
            if state == "stopping":
                time.sleep(30)
            info("Build instance stopped. Verifying S3 upload...")
            # Check for the split-archive manifest (new format)
            verify = _aws(config, "s3", "ls", manifest_uri)
            if verify.stdout.strip():
                success("Cache built and uploaded successfully!")
                # List all chunk files for summary
                chunk_list = _aws(config, "s3", "ls", f"s3://{config['s3_bucket']}/{s3_prefix}/")
                if chunk_list.stdout.strip():
                    for line in chunk_list.stdout.strip().splitlines():
                        info(f"  {line.strip()}")
            else:
                if state != "terminated":
                    _aws(config, "ec2", "terminate-instances", "--instance-ids", instance_id)
                fatal(
                    f"Build failed — cache manifest not found at {manifest_uri}.\n"
                    f"  Start instance to debug:\n"
                    f"    aws ec2 start-instances --instance-ids {instance_id} "
                    f"--profile {config['aws_profile']} --region {config['region']}\n"
                    f"  Then: sudo cat /var/log/sandbox-build-cache.log"
                )
            if state != "terminated":
                info(f"Terminating build instance...")
                _aws(config, "ec2", "terminate-instances", "--instance-ids", instance_id)
            return

        elapsed_min = elapsed // 60
        if elapsed_min > 0 and elapsed % 60 == 0:
            info(f"  [{elapsed_min}m] Instance state: {state}")

        time.sleep(interval)
        elapsed += interval

    error(f"Build timed out after {timeout // 60} minutes.")
    info(f"Terminating instance {instance_id}...")
    _aws(config, "ec2", "terminate-instances", "--instance-ids", instance_id)
    sys.exit(1)
