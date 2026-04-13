#!/usr/bin/env python3
"""
Sandbox container entrypoint.

Four modes, dispatched at the bottom of this file:

  1. Root phase (UID 0): create sandbox user, seed SSH/git config, re-exec
     as the sandbox user. Workspace is already populated by bin/sandbox.
  2. User phase (default): launch tmux with claude immediately in window 0
     and a setup window in window 1; PID 1 poll-blocks on the tmux session.
  3. Setup phase (SANDBOX_MODE=setup): runs in tmux window 1. Installs deps
     (Python/Node/Rust in parallel), migrates, seeds demo data, spawns the
     phrocs window, then exec's into bash -l so the window stays usable.
  4. Cache-init phase (SANDBOX_MODE=cache-init): one-shot cache warming for
     `bin/sandbox create` — installs deps, migrates, generates demo data,
     pre-builds Rust, then exits so the host can snapshot databases.
"""

from __future__ import annotations

import os
import sys
import stat
import time
import shutil
import traceback
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from textwrap import dedent

WORKSPACE = Path("/workspace")
SANDBOX_HOME = Path("/tmp/sandbox-home")
PROGRESS_FILE = Path("/tmp/sandbox-progress")

# Shown in tmux status bar, polled every 2s by tmux.sandbox.conf.
STATUS_FILE = Path("/tmp/sandbox-status")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts() -> str:
    return time.strftime("%H:%M:%S", time.gmtime())


def log(msg: str) -> None:
    """Print to container stdout only (root phase)."""
    print(f"[{_ts()}] ==> {msg}", flush=True)  # noqa: T201


def info(msg: str) -> None:
    """Log to stdout and write to progress file for the host script."""
    print(f"[{_ts()}] ==> {msg}", flush=True)  # noqa: T201
    with PROGRESS_FILE.open("a") as f:
        f.write(f"[{_ts()}] ==> {msg}\n")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kwargs)


def run_quiet(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, capture_output=True)


def write_file(path: Path, content: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if mode is not None:
        path.chmod(mode)


def write_file_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        write_file(path, content)


def _write_status(step: str) -> None:
    """Update the tmux status bar label. Swallows OSError — purely cosmetic."""
    try:
        STATUS_FILE.write_text(step)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Root phase — runs as UID 0
# ---------------------------------------------------------------------------


def create_sandbox_user(uid: int, gid: int) -> None:
    """Create passwd/group/shadow entries so tools resolve the UID."""
    if run_quiet(["getent", "passwd", str(uid)]).returncode == 0:
        return

    with open("/etc/passwd", "a") as f:
        f.write(f"sandbox:x:{uid}:{gid}:sandbox:{SANDBOX_HOME}:/bin/bash\n")
    if run_quiet(["getent", "group", str(gid)]).returncode != 0:
        with open("/etc/group", "a") as f:
            f.write(f"sandbox:x:{gid}:\n")
    with open("/etc/shadow", "a") as f:
        f.write("sandbox:*:19000:0:99999:7:::\n")


def export_environment(uid: int, gid: int) -> None:
    """Write env vars to /etc/environment and /etc/profile.d for SSH sessions."""
    extra_vars = {
        "HOME": str(SANDBOX_HOME),
        "UV_CACHE_DIR": "/cache/uv",
        "UV_LINK_MODE": "copy",
        "XDG_CACHE_HOME": "/tmp/sandbox-cache",
        "CARGO_TARGET_DIR": "/cache/cargo-target",
        "npm_config_store_dir": "/cache/pnpm",
        "COREPACK_ENABLE_AUTO_PIN": "0",
        "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0",
    }
    skip = {"HOSTNAME", "TERM", "SHELL", "PWD", "SHLVL", "_", "OLDPWD", "HOME", "USER", "LOGNAME"}

    lines = [f"{k}={v}" for k, v in os.environ.items() if k not in skip]
    lines.extend(f"{k}={v}" for k, v in extra_vars.items())

    Path("/etc/environment").write_text("\n".join(lines) + "\n")
    Path("/etc/profile.d/sandbox-env.sh").write_text("\n".join(f"export {line}" for line in lines) + "\n")


def _configure_ssh_agent_env() -> None:
    """Set SSH_AUTH_SOCK only if /ssh-agent is a real socket (not /dev/null fallback)."""
    if Path("/ssh-agent").exists() and stat.S_ISSOCK(Path("/ssh-agent").lstat().st_mode):
        os.environ["SSH_AUTH_SOCK"] = "/ssh-agent"
    else:
        os.environ.pop("SSH_AUTH_SOCK", None)


def configure_user_ssh(uid: int, gid: int) -> None:
    """Seed ~/.ssh/config so git push doesn't hang on a host-key prompt in tmux."""
    ssh_dir = SANDBOX_HOME / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    config = ssh_dir / "config"
    config.write_text(
        dedent("""\
            Host github.com
                StrictHostKeyChecking accept-new
                UserKnownHostsFile ~/.ssh/known_hosts
            """)
    )
    ssh_dir.chmod(0o700)
    config.chmod(0o600)
    run(["chown", "-R", f"{uid}:{gid}", str(ssh_dir)])


def start_sshd(uid: int, gid: int) -> None:
    """Start sshd if authorized keys are present."""
    keys = Path("/tmp/sandbox-authorized-keys")
    if not keys.exists() or keys.stat().st_size == 0:
        return

    ssh_dir = SANDBOX_HOME / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(keys, ssh_dir / "authorized_keys")
    ssh_dir.chmod(0o700)
    (ssh_dir / "authorized_keys").chmod(0o600)
    run(["chown", "-R", f"{uid}:{gid}", str(ssh_dir)])

    run(
        [
            "/usr/sbin/sshd",
            "-p",
            "2222",
            "-o",
            "PidFile=/tmp/sshd.pid",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "PermitRootLogin=no",
        ]
    )
    log("sshd listening on port 2222")


def copy_claude_auth(uid: int, gid: int) -> None:
    """Copy Claude Code auth files into the sandbox home."""
    claude_dir = SANDBOX_HOME / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    for name in (".credentials.json", "settings.json", "settings.local.json"):
        src = Path(f"/tmp/claude-auth/{name}")
        if src.exists():
            shutil.copy2(src, claude_dir / name)

    src = Path("/tmp/claude-auth.json")
    if src.exists():
        shutil.copy2(src, SANDBOX_HOME / ".claude.json")

    run(["chown", "-R", f"{uid}:{gid}", str(SANDBOX_HOME)])


def copy_host_gitconfig(uid: int, gid: int) -> None:
    """Copy host ~/.gitconfig and rewrite signing paths for the container.

    Copied (not mounted) so ``git config --global`` works without leaking
    back to the host. Signing paths (user.signingkey, allowedSignersFile)
    are rewritten to their in-container mount locations.
    """
    src = Path("/tmp/host-gitconfig")
    if not src.is_file():
        return
    dst = SANDBOX_HOME / ".gitconfig"
    shutil.copy2(src, dst)
    run(["chown", f"{uid}:{gid}", str(dst)])

    # Rewrite host-absolute paths to in-container mount paths.
    # Compose mounts /dev/null when unconfigured, so is_file() is correct.
    rewrites = {
        "user.signingkey": Path("/tmp/host-git-signingkey"),
        "gpg.ssh.allowedSignersFile": Path("/tmp/host-allowed-signers"),
    }
    for config_key, mount_path in rewrites.items():
        if mount_path.is_file():
            run(["git", "config", "--file", str(dst), config_key, str(mount_path)])


def root_phase() -> None:
    uid = int(os.environ.get("SANDBOX_UID", "1000"))
    gid = int(os.environ.get("SANDBOX_GID", "1000"))

    SANDBOX_HOME.mkdir(parents=True, exist_ok=True)
    Path("/tmp/sandbox-cache").mkdir(parents=True, exist_ok=True)
    # Start interactive shells in the workspace, not the dotfiles-only home dir.
    (SANDBOX_HOME / ".bashrc").write_text(f"cd {WORKSPACE}\n")
    run(["chown", f"{uid}:{gid}", str(SANDBOX_HOME), "/tmp/sandbox-cache"])

    create_sandbox_user(uid, gid)

    # Must run before export_environment snapshots os.environ into /etc/profile.d.
    _configure_ssh_agent_env()
    export_environment(uid, gid)

    # cache-init doesn't need SSH, auth, or IDE config.
    if os.environ.get("SANDBOX_MODE") != "cache-init":
        start_sshd(uid, gid)
        configure_user_ssh(uid, gid)
        copy_claude_auth(uid, gid)
        copy_host_gitconfig(uid, gid)

    # Re-exec as the sandbox user.
    os.execvp("gosu", ["gosu", f"{uid}:{gid}", sys.executable, __file__, *sys.argv[1:]])


# ---------------------------------------------------------------------------
# User phase — runs as the sandbox UID
# ---------------------------------------------------------------------------


def _run_captured(label: str, cmd: list[str], **kwargs) -> None:
    """Run a subprocess, suppressing output on success, dumping it on failure."""
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode == 0:
        return
    info(f"ERROR: {label} failed:")
    for line in (result.stdout or "").strip().splitlines():
        info(f"  {line}")
    for line in (result.stderr or "").strip().splitlines():
        info(f"  {line}")
    raise subprocess.CalledProcessError(result.returncode, cmd)


def install_python_deps() -> None:
    info("Started: uv sync...")
    _write_status("installing python deps")
    _run_captured("uv sync", ["uv", "sync", "--no-editable"])
    info("Finished: uv sync.")
    # Make hogli available — normally done by flox on-activate.sh.
    hogli_link = Path("/cache/python/bin/hogli")
    hogli_link.unlink(missing_ok=True)
    hogli_link.symlink_to("/workspace/bin/hogli")
    phrocs_link = WORKSPACE / "bin/phrocs"
    if not phrocs_link.exists():
        phrocs_link.symlink_to("/usr/local/bin/phrocs")


def install_node_deps() -> None:
    info("Started: pnpm install...")
    _write_status("installing node deps")
    # CI=1 suppresses interactive prompts. --no-frozen-lockfile is needed
    # because the sandbox branch may have different dependencies than the cache.
    _run_captured(
        "pnpm install",
        ["pnpm", "install", "--no-frozen-lockfile"],
        env={**os.environ, "CI": "1"},
    )
    info("Finished: pnpm install.")


def fetch_rust_crates() -> None:
    """Pre-fetch Rust crate sources so concurrent cargo builds don't race."""
    info("Started: cargo fetch...")
    _write_status("fetching rust crates")
    _run_captured("cargo fetch", ["cargo", "fetch"], cwd=str(WORKSPACE / "rust"))
    info("Finished: cargo fetch.")


def ensure_demo_data() -> None:
    """Generate demo data on first boot; skip if already present."""
    result = run_quiet(
        [
            "psql",
            "-h",
            "db",
            "-U",
            "posthog",
            "-d",
            "posthog",
            "-tAc",
            "SELECT 1 FROM posthog_user WHERE email='test@posthog.com' LIMIT 1",
        ]
    )
    if result.stdout.strip() == b"1":
        info("Demo data already present, skipping generation.")
    else:
        info("Generating demo data (first boot)...")
        run(["python", "manage.py", "generate_demo_data"])


def install_geoip() -> None:
    """Symlink GeoIP database from the Docker image into the worktree.

    The .json sidecar prevents bin/start's download-mmdb from clobbering
    the symlink and re-fetching on every boot.
    """
    share = WORKSPACE / "share"
    share.mkdir(parents=True, exist_ok=True)

    mmdb = share / "GeoLite2-City.mmdb"
    if not mmdb.exists() and not mmdb.is_symlink():
        mmdb.symlink_to("/share/GeoLite2-City.mmdb")

    sidecar = share / "GeoLite2-City.json"
    if not sidecar.exists():
        sidecar.write_text(f'{{ "date": "{time.strftime("%Y-%m-%d")}" }}\n')


def create_kafka_topics() -> None:
    info("Pre-creating Kafka topics...")
    for topic in ("clickhouse_events_json", "exceptions_ingestion"):
        if run_quiet(["rpk", "topic", "describe", topic, "--brokers", "kafka:9092"]).returncode != 0:
            run(["rpk", "topic", "create", topic, "--brokers", "kafka:9092", "-p", "1", "-r", "1"])


def generate_mprocs_config() -> None:
    info("Generating mprocs config...")
    config_dir = WORKSPACE / ".posthog/.generated"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "mprocs.yaml"

    # Seed intents on first boot; on restart, reuse the saved config.
    needs_seed = not config_file.exists()
    if not needs_seed:
        needs_seed = "_posthog:" not in config_file.read_text()

    if needs_seed:
        intents = os.environ.get("SANDBOX_INTENTS", "product_analytics")
        info(f"Seeding intents: {intents}")
        # Write seed YAML directly — system python doesn't have PyYAML or
        # hogli installed, and the structure is simple enough to emit by hand.
        lines = ["_posthog:", "  intents:"]
        for intent in intents.split(","):
            lines.append(f"  - {intent.strip()}")
        # Migrations already ran in the entrypoint; skip autostart to avoid
        # redundant Django startup overhead in phrocs.
        lines.append("  skip_autostart:")
        lines.append("  - migrate-postgres")
        lines.append("  - migrate-clickhouse")
        lines.append("  - migrate-persons-db")
        lines.append("procs: {}")
        config_file.write_text("\n".join(lines) + "\n")

    _run_captured("hogli dev:generate", ["hogli", "dev:generate"])


def _read_jetbrains_data_dir_name() -> str:
    """Read the config directory name from the installed IDE's product-info.json."""
    import json

    product_info = Path("/opt/idea/product-info.json")
    data = json.loads(product_info.read_text())
    data_dir_name = data["dataDirectoryName"]
    return data_dir_name


def setup_jetbrains_background() -> None:
    """Register JetBrains IDE backend in a background process."""
    idea_script = Path("/opt/idea/bin/remote-dev-server.sh")
    if not idea_script.exists():
        return

    data_dir_name = _read_jetbrains_data_dir_name()

    pid = os.fork()
    if pid != 0:
        return  # Parent continues

    # Child: redirect stdio to log so late writes don't clobber the tmux prompt.
    log_path = "/tmp/sandbox-jetbrains.log"
    log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    os.close(log_fd)

    os.environ["JAVA_TOOL_OPTIONS"] = f"-Duser.home={SANDBOX_HOME}"

    info(f"Registering {data_dir_name} for Gateway (background)...")
    result = subprocess.run(
        ["remote-dev-server.sh", "registerBackendLocationForGateway"],
        executable=str(idea_script),
        env={**os.environ, "REMOTE_DEV_NON_INTERACTIVE": "1"},
    )
    if result.returncode != 0:
        print(f"[{_ts()}] ERROR: IDE backend registration failed (exit {result.returncode}).")  # noqa: T201

    # Install Python plugin if not already present
    jetbrains_dir = SANDBOX_HOME / ".local/share/JetBrains"
    has_python_plugin = any(jetbrains_dir.rglob("python*")) if jetbrains_dir.exists() else False
    if not has_python_plugin:
        info("Installing Python plugin...")
        result = subprocess.run(
            [
                "remote-dev-server.sh",
                "installPlugins",
                "PythonCore",
                "Pythonid",
                "intellij.python.dap.plugin",
                "com.intellij.python.django",
            ],
            executable=str(idea_script),
            env={**os.environ, "REMOTE_DEV_NON_INTERACTIVE": "1"},
        )
        if result.returncode != 0:
            print(f"[{_ts()}] ERROR: Plugin installation failed (exit {result.returncode}).")  # noqa: T201

    # Configure Python SDK using the IDE's own config directory name
    idea_config = SANDBOX_HOME / ".config/JetBrains" / data_dir_name
    write_file_if_missing(
        idea_config / "options/jdk.table.xml",
        dedent("""\
            <application>
              <component name="ProjectJdkTable">
                <jdk version="2">
                  <name value="Python 3.12 (sandbox)" />
                  <type value="Python SDK" />
                  <homePath value="/cache/python/bin/python3" />
                  <roots>
                    <classPath><root type="composite" /></classPath>
                    <sourcePath><root type="composite" /></sourcePath>
                  </roots>
                  <additional />
                </jdk>
              </component>
            </application>
        """),
    )

    write_file_if_missing(
        WORKSPACE / ".idea/modules.xml",
        dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <project version="4">
              <component name="ProjectModuleManager">
                <modules>
                  <module fileurl="file://$PROJECT_DIR$/.idea/posthog.iml" filepath="$PROJECT_DIR$/.idea/posthog.iml" />
                </modules>
              </component>
            </project>
        """),
    )

    write_file_if_missing(
        WORKSPACE / ".idea/misc.xml",
        dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <project version="4">
              <component name="ProjectRootManager" version="2" project-jdk-name="Python 3.12 (sandbox)" project-jdk-type="Python SDK" />
              <component name="TestRunnerService">
                <option name="PROJECT_TEST_RUNNER" value="py.test" />
              </component>
            </project>
        """),
    )

    info(f"{data_dir_name} backend ready")
    os._exit(0)


def _setup_user_env() -> None:
    """Shared env setup for user_phase and cache_init_phase."""
    PROGRESS_FILE.write_text("")
    os.environ.update(
        {
            "HOME": str(SANDBOX_HOME),
            "UV_CACHE_DIR": "/cache/uv",
            "UV_LINK_MODE": "copy",
            "XDG_CACHE_HOME": "/tmp/sandbox-cache",
            "COREPACK_ENABLE_AUTO_PIN": "0",
            "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0",
            "CARGO_TARGET_DIR": "/cache/cargo-target",
            "npm_config_store_dir": "/cache/pnpm",
        }
    )
    _configure_ssh_agent_env()
    Path("/cache/cargo-target").mkdir(parents=True, exist_ok=True)
    os.chdir(WORKSPACE)
    # pushInsteadOf (not insteadOf) so anonymous HTTPS fetches still work
    # for cargo deps that clone without an SSH agent during cache-init.
    run(["git", "config", "--global", "url.git@github.com:.pushInsteadOf", "https://github.com/"])


def _run_parallel(tasks: dict[str, Callable[[], None]]) -> None:
    """Run named tasks in parallel, re-raising the first failure."""
    with ThreadPoolExecutor() as pool:
        futures = {pool.submit(fn): name for name, fn in tasks.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"[{_ts()}] ERROR: {name} failed: {e}", flush=True)  # noqa: T201
                raise


def user_phase() -> None:
    """PID 1: launch tmux (claude + setup windows), then poll-block on the session."""
    _setup_user_env()
    install_geoip()

    _write_status("booting")

    # Window 0: claude (launched immediately, may lack hogli until uv sync finishes)
    # Window 1: setup (deps, migrations, then spawns phrocs in window 2)
    tmux = ["tmux", "-L", "sandbox"]
    run(
        [
            *tmux,
            "-f",
            "/etc/tmux.sandbox.conf",
            "new-session",
            "-d",
            "-s",
            "posthog",
            "-c",
            "/workspace",
            "-n",
            "claude",
            "claude",
        ]
    )
    # Auto-respawn on crash (pairs with pane-died hook in tmux.sandbox.conf).
    # Scoped to claude window only so setup/phrocs close normally.
    run([*tmux, "set-window-option", "-t", "posthog:claude", "remain-on-exit", "on"])

    run(
        [
            *tmux,
            "new-window",
            "-t",
            "posthog:",
            "-n",
            "setup",
            "-e",
            "SANDBOX_MODE=setup",
            f"{sys.executable} {__file__}",
        ]
    )
    run([*tmux, "select-window", "-t", "posthog:claude"])

    # Block on tmux session. Exit non-zero when it dies so compose's
    # restart: on-failure brings the container back.
    while (
        subprocess.run(
            [*tmux, "has-session", "-t", "posthog"],
            capture_output=True,
        ).returncode
        == 0
    ):
        time.sleep(2)
    sys.exit(1)


def run_setup() -> None:
    """Tmux window 1: install deps, migrate, seed data, spawn phrocs, exec bash.

    On failure, writes "SETUP FAILED" to the status bar and drops into bash
    so the user can diagnose. Claude keeps running in window 0 either way.
    """
    _setup_user_env()
    _write_status("setup starting")

    try:
        # Kafka is health-gated by compose, safe to call early.
        create_kafka_topics()

        def install_python_and_migrate() -> None:
            install_python_deps()
            _write_status("running migrations")
            run(["python", "manage.py", "sandbox_migrate", "--progress-file", str(PROGRESS_FILE)])
            _write_status("seeding demo data")
            ensure_demo_data()

        _run_parallel(
            {
                "python deps + migrations": install_python_and_migrate,
                "node deps": install_node_deps,
                "rust crates": fetch_rust_crates,
            }
        )

        # generate_mprocs_config needs the hogli symlink created by install_python_deps.
        generate_mprocs_config()

        # Forks internally — must run after ThreadPoolExecutor is closed.
        try:
            setup_jetbrains_background()
        except Exception as e:
            # Loud but non-fatal — IDE setup failing should not prevent the sandbox from booting.
            print(f"[{_ts()}] ERROR: JetBrains IDE setup failed: {e}", flush=True)  # noqa: T201

        lock = WORKSPACE / "bin/start.lock"
        lock.unlink(missing_ok=True)

        _write_status("sandbox ready")

        # Spawn phrocs in its own tmux window.
        run(["tmux", "-L", "sandbox", "new-window", "-t", "posthog:", "-n", "phrocs", "bin/start --phrocs"])

        print(  # noqa: T201
            "\nSetup complete — phrocs running in window 2 (Ctrl-b 2), Claude in window 0 (Ctrl-b 0).\n",
            flush=True,
        )
    except Exception:
        traceback.print_exc()
        _write_status("!! SETUP FAILED — see window 1")
        print(  # noqa: T201
            "\n\n!!! Setup failed — traceback above. This window is now a bash shell;"
            "\n!!! claude is still running in window 0 against whatever managed to come up."
            "\n!!! Re-run the failing step manually, then `tmux new-window bin/start --phrocs` when ready.\n",
            flush=True,
        )

    # Exec into bash so this window stays usable (both success and failure).
    os.execvp("bash", ["bash", "-l"])


# ---------------------------------------------------------------------------
# Cache-init phase — one-shot cache warming for `bin/sandbox create`
# ---------------------------------------------------------------------------


def cache_init_phase() -> None:
    """Warm all shared caches (uv, pnpm store, cargo target) and populate databases.

    Runs inside `compose run` during `bin/sandbox create` when no database cache
    exists. Exits when done so the host script can snapshot Postgres + ClickHouse.
    """
    _setup_user_env()

    def install_python_and_migrate() -> None:
        install_python_deps()
        info("Running migrations...")
        run(["python", "manage.py", "sandbox_migrate", "--progress-file", str(PROGRESS_FILE)])
        info("Generating demo data (this takes a few minutes)...")
        run(["python", "manage.py", "generate_demo_data", "--skip-flag-sync"])

    def build_rust() -> None:
        info("Pre-building Rust workspace...")
        try:
            run(["cargo", "build", "--workspace"], cwd=str(WORKSPACE / "rust"))
            info("Finished: cargo build.")
        except subprocess.CalledProcessError as e:
            # Non-fatal: even a partial build warms the cargo cache for subsequent
            # boots. Cargo's stderr already streamed to the terminal so the error
            # details are visible above; we just need to preserve the exit code
            # for debugging.
            info(f"Rust pre-build failed (exit {e.returncode}), continuing (cargo cache still warmed).")

    # Python path is usually the critical path (migrations on a fresh DB take
    # several minutes) so we want node + rust overlapping with it.
    _run_parallel(
        {
            "python + migrations + demo data": install_python_and_migrate,
            "node deps": install_node_deps,
            "rust build": build_rust,
        }
    )

    info("Cache init complete.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mode = os.environ.get("SANDBOX_MODE")
    uid = int(os.environ.get("SANDBOX_UID", "1000"))
    if os.getuid() == 0 and uid != 0:
        root_phase()
    elif mode == "cache-init":
        cache_init_phase()
    elif mode == "setup":
        run_setup()
    else:
        user_phase()
