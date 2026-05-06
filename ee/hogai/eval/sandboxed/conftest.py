from __future__ import annotations

import os
import time
import atexit
import socket
import asyncio
import logging
import threading
import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest

from django.conf import settings

from posthog.temporal.common.worker import create_worker

from products.tasks.backend.services.custom_prompt_internals import CustomPromptSandboxContext
from products.tasks.backend.services.local_skills import ENV_LOCAL_SKILLS_HOST_PATH, LocalSkillsCache
from products.tasks.backend.temporal import (
    ACTIVITIES as TASKS_ACTIVITIES,
    WORKFLOWS as TASKS_WORKFLOWS,
)

# We want the PostHog set_up_evals fixture here
from ee.hogai.eval.conftest import set_up_evals  # noqa: F401
from ee.hogai.eval.data_setup import copy_demo_data_to_new_team, create_core_memory, ensure_master_demo_team

logger = logging.getLogger(__name__)

MCP_PORT = 18787  # Non-default port to avoid conflicts with dev MCP
DJANGO_LIVE_PORT = 18000  # Non-default port for in-process Django server
LLM_GATEWAY_PORT = 13308  # Non-default port to avoid conflicts with dev LLM gateway

# Sandboxed evals issue HogQL validation that touches the `persons_db_*`
# replicas (the validator opens connections even when the query itself
# doesn't read persons). pytest-django defaults a test's allowed
# databases to ``{"default"}`` only, so without this whitelist
# `execute-sql` raises an internal error. Applied via
# ``pytest_collection_modifyitems`` below so individual evals don't have
# to repeat it on every ``@pytest.mark.django_db`` marker.
SANDBOXED_EVAL_DATABASES = ("default", "persons_db_writer", "persons_db_reader")


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    """Auto-extend ``@pytest.mark.django_db`` for every sandboxed eval.

    Tests under this directory transparently get access to the persons
    replicas. If a test ever needs a narrower whitelist it can set
    ``databases=...`` on its own marker — explicit kwargs win.

    Prepended via ``append=False`` so it beats the function-level
    ``@pytest.mark.django_db`` in pytest's ``iter_markers``/``get_closest_marker``
    resolution; otherwise the original (no-kwargs) marker is read first
    and pytest-django defaults ``databases`` back to ``{"default"}``.

    This piggybacks on the same ``pytest_collection_modifyitems`` hook
    that ``mcp_mode`` parametrization uses.
    """
    base_dir = Path(__file__).parent
    for item in items:
        try:
            test_path = Path(str(item.fspath))
            test_path.relative_to(base_dir)
        except (TypeError, ValueError):
            continue
        existing = item.get_closest_marker("django_db")
        if existing is not None and "databases" in existing.kwargs:
            continue  # respect explicit per-test override
        args = existing.args if existing is not None else ()
        kwargs = {**(existing.kwargs if existing is not None else {}), "databases": list(SANDBOXED_EVAL_DATABASES)}
        item.add_marker(pytest.mark.django_db(*args, **kwargs), append=False)


# Sandbox container name prefix used by the eval harness (set in SandboxConfig.name)
_EVAL_CONTAINER_PREFIX = "task-sandbox-"


def _cleanup_eval_containers():
    """Remove any leftover eval Docker containers.

    Registered via ``atexit`` so it runs even on Ctrl+C / SIGINT where
    pytest session teardown may be skipped.
    """
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={_EVAL_CONTAINER_PREFIX}", "--format", "{{.ID}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for container_id in result.stdout.strip().splitlines():
            if container_id:
                logger.info("Cleaning up eval container %s", container_id)
                subprocess.run(["docker", "rm", "-f", container_id], capture_output=True, timeout=10)
    except Exception:
        pass  # Best effort — don't crash the exit path


@pytest.fixture(scope="session", autouse=True)
def _cleanup_sandbox_containers(pytestconfig):
    """Stop and remove any eval sandbox containers at session end. Sandboxes are kept alive, but evals should not keep them.

    Registers an ``atexit`` hook as a belt-and-braces safety net for SIGINT /
    SIGTERM paths where pytest's session teardown is skipped. Pass
    ``--keep-sandbox-containers`` to opt out (useful when debugging a
    leftover container).
    """
    keep = pytestconfig.option.keep_sandbox_containers
    if not keep:
        atexit.register(_cleanup_eval_containers)
    yield
    if keep:
        logger.info("--keep-sandbox-containers set, skipping container cleanup")
        return
    _cleanup_eval_containers()


@pytest.fixture(scope="session", autouse=True)
def _django_live_server(django_db_setup, django_db_blocker):
    """Start an in-process Django HTTP server on the test database.

    Uses Django's ``LiveServerThread`` (same mechanism as pytest-django's
    ``live_server`` fixture, but session-scoped). The sandbox Docker container
    calls this server via ``host.docker.internal`` for API requests,
    log persistence, and the LLM gateway.

    Depends on ``django_db_setup`` so the test database is created before
    any subprocess (LLM gateway, MCP) tries to connect to it.
    """
    from pytest_django.live_server_helper import LiveServer

    django_db_blocker.unblock()

    server = LiveServer(f"localhost:{DJANGO_LIVE_PORT}")
    logger.info("Django live server started at %s", server.url)

    yield server

    server.stop()
    django_db_blocker.restore()
    logger.info("Django live server stopped")


@pytest.fixture(scope="session", autouse=True)
def _sandboxed_local_skills(_sandbox_settings) -> Generator[Path, None, None]:
    """Build local skills once per session; bind-mount into every sandbox.

    Uses a content-hash cache so repeat runs skip the build when nothing has
    changed. Sets ``SANDBOX_LOCAL_SKILLS_HOST_PATH`` so ``DockerSandbox`` can
    pick it up when provisioning containers — keeping the base image stable
    while letting eval authors iterate on skills without rebuilding it.

    Depends on ``_sandbox_settings`` so the ``DEBUG=True`` override is active
    when the skill renderer runs — some template helpers (e.g. HogQL example
    rendering) guard on that setting.
    """
    cache = LocalSkillsCache()
    dist_dir = cache.ensure_built()
    previous = os.environ.get(ENV_LOCAL_SKILLS_HOST_PATH)
    os.environ[ENV_LOCAL_SKILLS_HOST_PATH] = str(dist_dir)
    try:
        yield dist_dir
    finally:
        if previous is None:
            os.environ.pop(ENV_LOCAL_SKILLS_HOST_PATH, None)
        else:
            os.environ[ENV_LOCAL_SKILLS_HOST_PATH] = previous


@pytest.fixture(scope="session", autouse=True)
def _sandbox_settings(_django_live_server, _llm_gateway):
    """Configure Django settings required by the sandbox/temporal activities.

    All URLs use ``host.docker.internal`` so they're reachable from inside
    Docker sandbox containers. Points at the in-process Django live server
    which shares the test database.

    Also patches ``posthoganalytics.feature_enabled`` to return True for all
    flags so permission checks (TasksAccessPermission) and workflow guards pass.
    """
    from unittest.mock import patch

    from django.test import override_settings

    # Docker containers reach the host via host.docker.internal
    docker_api_url = f"http://host.docker.internal:{DJANGO_LIVE_PORT}"
    docker_llm_gateway_url = f"http://host.docker.internal:{LLM_GATEWAY_PORT}"

    import posthoganalytics

    with (
        override_settings(
            DEBUG=True,  # Required for sandbox URL validation to allow http://localhost
            SANDBOX_PROVIDER="docker",
            SANDBOX_API_URL=docker_api_url,
            SANDBOX_LLM_GATEWAY_URL=docker_llm_gateway_url,
            SANDBOX_MCP_URL=f"http://host.docker.internal:{MCP_PORT}/mcp",
        ),
        patch.object(posthoganalytics, "feature_enabled", return_value=True),
    ):
        yield


# MCP mode selection — see `--mcp-mode` option in ee/hogai/eval/conftest.py.
# The PostHog MCP server can register tools individually ("tools" mode) or
# wrap them all behind a single `exec` tool ("cli" mode). Each sandboxed
# eval is parametrized across both modes by default so we can compare
# agent behavior across the two surfaces in a single run.


def pytest_generate_tests(metafunc):
    """Parametrize sandboxed tests across the requested MCP execution modes.

    Triggered for any test whose dependency graph touches ``mcp_mode`` —
    which covers every test under ``ee/hogai/eval/sandboxed/`` because the
    autouse ``_apply_mcp_mode`` fixture depends on it.
    """
    if "mcp_mode" not in metafunc.fixturenames:
        return
    option = metafunc.config.getoption("--mcp-mode")
    if option == "both":
        modes = ["tools", "cli"]
    else:
        modes = [option]
    metafunc.parametrize("mcp_mode", modes)


@pytest.fixture(autouse=True)
def _apply_mcp_mode(mcp_mode, _sandbox_settings):
    """Per-test override that pins the MCP execution mode.

    Appends ``?mode=<mcp_mode>`` to ``SANDBOX_MCP_URL`` so the MCP server
    registers either every tool individually (``tools``) or wraps them all
    in a single ``posthog`` exec tool (``cli``). The explicit query
    parameter wins over the feature-flag + client-profile heuristic in
    ``services/mcp/src/mcp.ts``, and the MCP service runs in a Cloudflare
    Worker outside this Python process — so a Python-side
    ``posthoganalytics.feature_enabled`` patch wouldn't reach it anyway.
    """
    from django.test import override_settings

    base = settings.SANDBOX_MCP_URL or ""
    sep = "&" if "?" in base else "?"
    moded_url = f"{base}{sep}mode={mcp_mode}"

    with override_settings(SANDBOX_MCP_URL=moded_url):
        yield mcp_mode


@pytest.fixture(scope="session", autouse=True)
def _terminate_stale_workflows(_sandbox_settings):
    """Terminate any stale temporal workflows left over from previous test runs.

    Without this, the in-process worker wastes time processing old workflows
    (creating sandboxes for runs that no longer exist in the test database),
    delaying the actual eval workflow by 30-60 seconds.
    """
    import asyncio as _asyncio

    from posthog.temporal.common.client import async_connect

    async def _terminate():
        client = await async_connect()
        terminated = 0
        async for wf in client.list_workflows(f'TaskQueue="{settings.TASKS_TASK_QUEUE}"'):
            try:
                handle = client.get_workflow_handle(wf.id, run_id=wf.run_id)
                await handle.terminate(reason="eval harness cleanup")
                terminated += 1
            except Exception:
                pass
        if terminated:
            logger.info("Terminated %d stale temporal workflows", terminated)

    _asyncio.run(_terminate())
    yield


@pytest.fixture(scope="session", autouse=True)
def _temporal_worker(_sandbox_settings, _terminate_stale_workflows, django_db_blocker):
    """Start an in-process temporal worker for the tasks queue.

    Mirrors the dev worker (``manage.py start_temporal_worker``) using
    ``create_worker``. Runs in a daemon thread. DB access is unblocked so
    temporal activities can use the Django ORM against the test database.
    """
    loop = asyncio.new_event_loop()
    stop_event = asyncio.Event()
    ready_event = threading.Event()

    async def _run():
        logger.info(
            "Starting eval temporal worker (%s:%s queue=%s)",
            settings.TEMPORAL_HOST,
            settings.TEMPORAL_PORT,
            settings.TASKS_TASK_QUEUE,
        )
        managed = await create_worker(
            host=settings.TEMPORAL_HOST,
            port=int(settings.TEMPORAL_PORT),
            metrics_port=0,
            namespace=settings.TEMPORAL_NAMESPACE,
            task_queue=settings.TASKS_TASK_QUEUE,
            workflows=TASKS_WORKFLOWS,
            activities=TASKS_ACTIVITIES,  # type: ignore[arg-type]
            max_concurrent_workflow_tasks=100,
            max_concurrent_activities=100,
            enable_combined_metrics_server=False,
        )
        logger.info("Eval temporal worker created")
        ready_event.set()
        worker_task = asyncio.ensure_future(managed.run())
        await stop_event.wait()
        logger.info("Shutting down eval temporal worker")
        await managed.shutdown()
        worker_task.cancel()

    # Unblock DB access for the worker thread and its activity thread pool
    django_db_blocker.unblock()

    thread = threading.Thread(target=loop.run_until_complete, args=(_run(),), daemon=True)
    thread.start()

    if not ready_event.wait(timeout=30):
        django_db_blocker.restore()
        pytest.fail(
            f"Temporal worker failed to start within 30s. "
            f"Is temporal running at {settings.TEMPORAL_HOST}:{settings.TEMPORAL_PORT}?"
        )

    logger.info("Eval temporal worker ready")
    yield

    loop.call_soon_threadsafe(stop_event.set)
    thread.join(timeout=10)
    django_db_blocker.restore()


@pytest.fixture(scope="session", autouse=True)
def _llm_gateway(_django_live_server, sandboxed_demo_data):
    """Start the LLM gateway as a subprocess.

    Mirrors ``bin/start-llm-gateway``: runs uvicorn on a non-default port.
    The sandbox's agent-server uses this to proxy LLM calls to Anthropic.
    """
    gateway_dir = Path(settings.BASE_DIR) / "services" / "llm-gateway"
    venv_dir = gateway_dir / ".venv"
    uvicorn_bin = venv_dir / "bin" / "uvicorn"

    if not uvicorn_bin.exists():
        pytest.fail(
            f"LLM gateway venv not found at {venv_dir}. "
            "Run `bin/start-llm-gateway` once or `cd services/llm-gateway && uv venv .venv && uv pip install -e .`"
        )
    # The LLM gateway uses pydantic BaseSettings with env_prefix="LLM_GATEWAY_".
    # DATABASE_URL and LLM_GATEWAY_ANTHROPIC_API_KEY come from the parent env
    # (e.g. .env.local / op run). We need to point it at the test database.
    from django.db import connections

    conn = connections["default"]
    # After django_db_setup runs, settings_dict["NAME"] is already rewritten to
    # the test DB name (pytest-django does this in-place), so don't re-prefix it.
    db_name = conn.settings_dict["NAME"]
    db_user = conn.settings_dict.get("USER", "posthog")
    db_password = conn.settings_dict.get("PASSWORD", "posthog")
    db_host = conn.settings_dict.get("HOST", "localhost")
    db_port = conn.settings_dict.get("PORT", "5432")
    test_db_url = f"postgres://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

    env = {
        **os.environ,
        "UV_PROJECT_ENVIRONMENT": str(venv_dir),
        "LLM_GATEWAY_DATABASE_URL": test_db_url,
        "LLM_GATEWAY_DEBUG": "true",
        "LLM_GATEWAY_TEAM_RATE_LIMIT_MULTIPLIERS": '{"1": 10}',
        "LLM_GATEWAY_POSTHOG_HOST": str(_django_live_server),
    }

    logger.info("Starting LLM gateway on port %d", LLM_GATEWAY_PORT)
    proc = subprocess.Popen(
        [
            str(uvicorn_bin),
            "llm_gateway.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(LLM_GATEWAY_PORT),
        ],
        cwd=gateway_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    def _pipe_to_logger(pipe, level):
        for line in iter(pipe.readline, b""):
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                logger.log(level, "[llm-gateway] %s", text)
        pipe.close()

    threading.Thread(target=_pipe_to_logger, args=(proc.stdout, logging.INFO), daemon=True).start()
    threading.Thread(target=_pipe_to_logger, args=(proc.stderr, logging.WARNING), daemon=True).start()

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            sock = socket.create_connection(("localhost", LLM_GATEWAY_PORT), timeout=1)
            sock.close()
            break
        except OSError:
            time.sleep(0.5)
    else:
        proc.terminate()
        proc.wait(timeout=5)
        pytest.fail(f"LLM gateway failed to start on port {LLM_GATEWAY_PORT} within 30s.")

    logger.info("LLM gateway ready on port %d", LLM_GATEWAY_PORT)
    yield

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    logger.info("LLM gateway stopped")


@pytest.fixture(scope="session", autouse=True)
def _mcp_server(_django_live_server, _sandbox_settings):
    """Start the MCP server as a subprocess for the eval session.

    Pointed at the in-process Django live server (which uses the test DB).
    Uses a non-default port to avoid conflicts with a running dev MCP server.
    """
    mcp_dir = Path(settings.BASE_DIR) / "services" / "mcp"
    if not (mcp_dir / "node_modules").exists():
        logger.info("Installing MCP server dependencies")
        subprocess.run(["pnpm", "install", "--frozen-lockfile"], cwd=mcp_dir, check=True, capture_output=True)

    api_url = str(_django_live_server)

    env = {
        **os.environ,
        "POSTHOG_API_BASE_URL": api_url,
        "MCP_APPS_BASE_URL": f"http://localhost:{MCP_PORT}",
        "POSTHOG_MCP_APPS_ANALYTICS_BASE_URL": api_url,
        "NODE_ENV": "development",
    }

    # Wrangler's .dev.vars file (committed) overrides process env, so we must
    # pass --var on the CLI to point the MCP at our in-process Django test DB.
    wrangler_vars = [
        f"POSTHOG_API_BASE_URL:{api_url}",
        f"POSTHOG_MCP_APPS_ANALYTICS_BASE_URL:{api_url}",
        f"MCP_APPS_BASE_URL:http://localhost:{MCP_PORT}",
    ]
    var_args: list[str] = []
    for v in wrangler_vars:
        var_args.extend(["--var", v])

    logger.info("Starting MCP server on port %d (API: %s)", MCP_PORT, api_url)
    proc = subprocess.Popen(
        ["pnpm", "wrangler", "dev", "--port", str(MCP_PORT), *var_args],
        cwd=mcp_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Stream subprocess output to logger in background threads
    def _pipe_to_logger(pipe, level):
        for line in iter(pipe.readline, b""):
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                logger.log(level, "[mcp] %s", text)
        pipe.close()

    threading.Thread(target=_pipe_to_logger, args=(proc.stdout, logging.INFO), daemon=True).start()
    threading.Thread(target=_pipe_to_logger, args=(proc.stderr, logging.WARNING), daemon=True).start()

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            sock = socket.create_connection(("localhost", MCP_PORT), timeout=1)
            sock.close()
            break
        except OSError:
            time.sleep(0.5)
    else:
        proc.terminate()
        proc.wait(timeout=5)
        pytest.fail(f"MCP server failed to start on port {MCP_PORT} within 30s.")

    logger.info("MCP server ready on port %d", MCP_PORT)
    yield

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    logger.info("MCP server stopped")


class SandboxedDemoData:
    """Session-scoped holder for master demo seed + per-case team factory.

    One instance per pytest session: seeds the master Hedgebox team (or reuses
    a healthy one), then produces a fresh isolated ``CustomPromptSandboxContext``
    for every eval case via ``make_context(label)``. Each call copies the master
    into a brand-new org/team/user with its own core memory and tasks-API
    access, so concurrent eval cases can't pollute each other's state.
    """

    def __init__(self, master_team_id: int, django_db_blocker, agent_model: str | None = None):
        self.master_team_id = master_team_id
        self._django_db_blocker = django_db_blocker
        self.agent_model = agent_model

    def make_context(self, case_label: str) -> CustomPromptSandboxContext:
        from products.tasks.backend.models import CodeInvite, CodeInviteRedemption

        org, team, user = copy_demo_data_to_new_team(self.master_team_id, self._django_db_blocker, label=case_label)
        create_core_memory(team, self._django_db_blocker)
        with self._django_db_blocker.unblock():
            invite, _ = CodeInvite.objects.get_or_create(code="eval-harness", max_redemptions=0, is_active=True)
            CodeInviteRedemption.objects.get_or_create(invite_code=invite, user=user, organization=org)
        logger.info("Case %r assigned team_id=%d user_id=%d", case_label, team.id, user.id)
        return CustomPromptSandboxContext(
            team_id=team.id,
            user_id=user.id,
            repository="posthog/hedgebox",
            model=self.agent_model,
        )


@pytest.fixture(scope="session", autouse=True)
def sandboxed_demo_data(
    set_up_evals,  # noqa: F811
    django_db_blocker,
    pytestconfig,
) -> SandboxedDemoData:
    """Seed the master Hedgebox team (once) and expose a per-case context factory."""
    from posthog.clickhouse.client import sync_execute

    master_team_id = ensure_master_demo_team(django_db_blocker)
    with django_db_blocker.unblock():
        rows = sync_execute(
            "SELECT event, count() FROM events WHERE team_id = %(team_id)s GROUP BY event ORDER BY 2 DESC LIMIT 20",
            {"team_id": master_team_id},
        )
    logger.info("Master demo ready: team_id=%d event_counts=%s", master_team_id, rows)

    agent_model = pytestconfig.getoption("--agent-model")
    logger.info("Sandboxed eval agent model pinned to %r", agent_model)
    return SandboxedDemoData(
        master_team_id=master_team_id,
        django_db_blocker=django_db_blocker,
        agent_model=agent_model,
    )


@pytest.fixture(scope="session")
def posthog_client() -> Generator:
    """PostHog analytics client for capturing eval traces and evaluation events to US production."""
    from posthog.ph_client import get_client

    client = get_client("US")
    yield client
    if client:
        client.shutdown()


def pytest_terminal_summary(terminalreporter, exitstatus, config):  # noqa: ARG001
    """Surface the local eval log directories at the end of a test session.

    Mirrors the Braintrust URL reporter pattern in ``ee/hogai/eval/conftest.py`` —
    gives an agent iterating on failing eval cases a single, obvious place to
    look for raw agent output without digging through per-test stdout capture.
    """
    log_dirs = getattr(config, "_sandboxed_eval_log_dirs", None)
    if not log_dirs:
        return

    writer = terminalreporter
    writer.write_sep("=", "sandboxed eval logs")
    writer.write_line("Raw agent logs written to:")
    for path in sorted(log_dirs):
        writer.write_line(f"  {path}")
    writer.write_line("Files per case: <case>.jsonl (raw), <case>.artifacts.json, <case>.summary.txt")
