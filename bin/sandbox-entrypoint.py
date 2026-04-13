#!/usr/bin/env python3
"""
Sandbox container entrypoint.

Two-phase startup:
  1. Root phase (UID 0): create sandbox user, configure system, bind-mount
     node_modules onto the cache volume, then re-exec as the sandbox user.
  2. User phase: install dependencies and launch mprocs inside tmux.

Alternate user-phase mode (SANDBOX_MODE=cache-init): install all dependencies,
run migrations, generate demo data, pre-build the Rust workspace, then exit.
Used by `bin/sandbox create` to populate shared cache volumes before snapshotting
the databases. Skips sshd/claude-auth/node_modules bind mount in the root phase
since they're not needed for a one-off cache build.
"""

from __future__ import annotations

import os
import sys
import time
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from textwrap import dedent

WORKSPACE = Path("/workspace")
SANDBOX_HOME = Path("/tmp/sandbox-home")
PROGRESS_FILE = Path("/tmp/sandbox-progress")

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


def bind_mount_node_modules(uid: int, gid: int) -> None:
    """Bind-mount node_modules dirs onto the /cache/node-modules volume.

    This redirects pnpm I/O from the slow VirtioFS bind mount to fast ext4
    storage inside the Docker VM.
    """
    log("Bind-mounting node_modules onto cache volume...")
    cache_root = Path("/cache/node-modules")

    for pkg_json in WORKSPACE.rglob("package.json"):
        # Skip anything inside node_modules or .git
        parts = pkg_json.parts
        if "node_modules" in parts or ".git" in parts:
            continue

        pkg_dir = pkg_json.parent
        rel = pkg_dir.relative_to(WORKSPACE)
        nm = pkg_dir / "node_modules"
        cache_dir = cache_root / rel

        nm.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)
        run(["chown", f"{uid}:{gid}", str(nm)])
        run(["mount", "--bind", str(cache_dir), str(nm)])

    run(["chown", "-R", f"{uid}:{gid}", str(cache_root)])


def root_phase() -> None:
    uid = int(os.environ.get("SANDBOX_UID", "1000"))
    gid = int(os.environ.get("SANDBOX_GID", "1000"))

    SANDBOX_HOME.mkdir(parents=True, exist_ok=True)
    Path("/tmp/sandbox-cache").mkdir(parents=True, exist_ok=True)
    # Start interactive shells in the workspace, not the dotfiles-only home dir.
    (SANDBOX_HOME / ".bashrc").write_text(f"cd {WORKSPACE}\n")
    run(["chown", f"{uid}:{gid}", str(SANDBOX_HOME), "/tmp/sandbox-cache"])

    create_sandbox_user(uid, gid)

    # The worktree's .git file points to a host path that doesn't exist in
    # the container. Fix it by bind-mounting a rewritten .git file that
    # points at /repo.git (where the main repo's .git is mounted).
    # This avoids setting GIT_DIR globally, which would poison every
    # subprocess that runs `git` (uv sync, cargo fetch, etc.).
    gitdir_line = (WORKSPACE / ".git").read_text().strip()
    worktree_name = gitdir_line.rsplit("/", 1)[-1]
    container_gitdir = f"/repo.git/worktrees/{worktree_name}"
    patched_gitfile = Path("/tmp/sandbox-gitfile")
    patched_gitfile.write_text(f"gitdir: {container_gitdir}\n")
    run(["mount", "--bind", str(patched_gitfile), str(WORKSPACE / ".git")])

    export_environment(uid, gid)

    # Skip steps that aren't needed for a one-off cache build (no SSH access,
    # no IDE, no pnpm install against a throwaway worktree).
    if os.environ.get("SANDBOX_MODE") != "cache-init":
        start_sshd(uid, gid)
        copy_claude_auth(uid, gid)
        bind_mount_node_modules(uid, gid)

    # Re-exec as the sandbox user.
    os.execvp("gosu", ["gosu", f"{uid}:{gid}", sys.executable, __file__, *sys.argv[1:]])


# ---------------------------------------------------------------------------
# User phase — runs as the sandbox UID
# ---------------------------------------------------------------------------


def install_python_deps() -> None:
    info("Started: uv sync...")
    result = subprocess.run(["uv", "sync", "--no-editable"], capture_output=True, text=True)
    if result.returncode != 0:
        info("ERROR: uv sync failed:")
        for line in (result.stdout or "").strip().splitlines():
            info(f"  {line}")
        for line in (result.stderr or "").strip().splitlines():
            info(f"  {line}")
        raise subprocess.CalledProcessError(result.returncode, result.args)
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
    # CI=1 suppresses interactive prompts. --no-frozen-lockfile is needed
    # because the sandbox branch may have different dependencies than the cache.
    run(
        ["pnpm", "install", "--no-frozen-lockfile"],
        env={**os.environ, "CI": "1"},
    )
    info("Finished: pnpm install.")


def fetch_rust_crates() -> None:
    """Pre-fetch Rust crate sources so concurrent cargo builds don't race."""
    info("Started: cargo fetch...")
    run(["cargo", "fetch"], cwd=str(WORKSPACE / "rust"))
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
    """Symlink the GeoIP database from the Docker image into the worktree."""
    mmdb = WORKSPACE / "share/GeoLite2-City.mmdb"
    if mmdb.exists() or mmdb.is_symlink():
        return
    mmdb.parent.mkdir(parents=True, exist_ok=True)
    mmdb.symlink_to("/share/GeoLite2-City.mmdb")


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

    subprocess.run(["hogli", "dev:generate"], capture_output=True)


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

    # Child process — runs in background
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
    """Shared env setup for user_phase and cache_init_phase.

    Sets cache directory env vars, ensures the cargo target dir exists, chdirs
    to /workspace, and marks the worktree as a safe git directory (the workspace
    is a bind mount owned by the host UID, which differs from the sandbox user,
    and Git 2.35.2+ refuses to operate in repos with mismatched ownership).
    """
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
    Path("/cache/cargo-target").mkdir(parents=True, exist_ok=True)
    os.chdir(WORKSPACE)
    run(["git", "config", "--global", "--add", "safe.directory", str(WORKSPACE)])


def user_phase() -> None:
    _setup_user_env()

    install_geoip()
    create_kafka_topics()

    # Run dependency installs in parallel.
    # Migrations and demo data are chained after Python deps (uv ~1.5s)
    # so they overlap with the slower pnpm/cargo installs.
    # On subsequent boots phrocs migration processes handle any new
    # migrations (usually a fast no-op).
    def install_python_and_migrate() -> None:
        install_python_deps()
        run(["python", "manage.py", "sandbox_migrate", "--progress-file", str(PROGRESS_FILE)])
        ensure_demo_data()

    with ThreadPoolExecutor() as pool:
        futures = {
            pool.submit(install_python_and_migrate): "python deps + migrations",
            pool.submit(install_node_deps): "node deps",
            pool.submit(fetch_rust_crates): "rust crates",
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"[{_ts()}] ERROR: {name} failed: {e}", flush=True)  # noqa: T201
                raise

    # generate_mprocs_config needs the hogli symlink created by install_python_deps.
    generate_mprocs_config()
    # setup_jetbrains_background uses os.fork(), which is unsafe inside a
    # ThreadPoolExecutor, so it runs after the pool is closed.
    try:
        setup_jetbrains_background()
    except Exception as e:
        # Loud but non-fatal — IDE setup failing should not prevent the sandbox from booting.
        print(f"[{_ts()}] ERROR: JetBrains IDE setup failed: {e}", flush=True)  # noqa: T201

    info("Starting PostHog via mprocs in tmux...")
    lock = WORKSPACE / "bin/start.lock"
    lock.unlink(missing_ok=True)

    os.execvp("tmux", ["tmux", "-L", "sandbox", "new-session", "-s", "posthog", "bin/start --phrocs"])


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
            run(
                ["cargo", "build", "--workspace"],
                cwd=str(WORKSPACE / "rust"),
            )
            info("Finished: cargo build.")
        except subprocess.CalledProcessError as e:
            # Non-fatal: even a partial build warms the cargo cache for subsequent
            # boots. Cargo's stderr already streamed to the terminal so the error
            # details are visible above; we just need to preserve the exit code
            # for debugging.
            info(f"Rust pre-build failed (exit {e.returncode}), continuing (cargo cache still warmed).")

    # Run all three cache-warming streams in parallel. Python path is usually
    # the critical path (migrations on a fresh DB take several minutes).
    with ThreadPoolExecutor() as pool:
        futures = {
            pool.submit(install_python_and_migrate): "python + migrations + demo data",
            pool.submit(install_node_deps): "node deps",
            pool.submit(build_rust): "rust build",
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"[{_ts()}] ERROR: {name} failed: {e}", flush=True)  # noqa: T201
                raise

    info("Cache init complete.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uid = int(os.environ.get("SANDBOX_UID", "1000"))
    if os.getuid() == 0 and uid != 0:
        root_phase()
    elif os.environ.get("SANDBOX_MODE") == "cache-init":
        cache_init_phase()
    else:
        user_phase()
