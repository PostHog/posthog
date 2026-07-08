from __future__ import annotations

import os
import json
import atexit
import asyncio
import logging
import threading
import subprocess
from collections.abc import Generator
from datetime import timedelta
from pathlib import Path

import pytest

from django.conf import settings

from temporalio.testing import WorkflowEnvironment

from posthog.temporal.common.worker import create_worker

from products.tasks.backend.facade.agents import (
    ENV_LOCAL_SKILLS_HOST_PATH,
    CustomPromptSandboxContext,
    LocalSkillsCache,
)
from products.tasks.backend.facade.temporal import (
    ACTIVITIES as TASKS_ACTIVITIES,
    WORKFLOWS as TASKS_WORKFLOWS,
)

# We want the PostHog set_up_evals fixture here
from ee.hogai.eval.conftest import set_up_evals  # noqa: F401
from ee.hogai.eval.data_setup import copy_demo_data_to_new_team, create_core_memory, ensure_master_demo_team
from ee.hogai.eval.sandboxed.long_lived_subprocess import LongLivedSubprocessManager

logger = logging.getLogger(__name__)

MCP_PORT = 18787  # Non-default port to avoid conflicts with dev MCP
DJANGO_LIVE_PORT = 18000  # Non-default port for in-process Django server
LLM_GATEWAY_PORT = 13308  # Non-default port to avoid conflicts with dev LLM gateway

# pytest-django normally derives this from ``@pytest.mark.django_db`` markers.
# Sandboxed evals intentionally strip those markers to avoid per-test DB
# transactions/flushes, so the local ``django_db_setup`` override below forces
# setup of the base Django DB explicitly. Person DB setup is handled by
# PostHog's eval setup after the default test DB name is known.
SANDBOXED_EVAL_SETUP_DATABASES: dict[str, None] = {"default": None}


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    """Keep sandboxed evals out of pytest-django's per-test DB wrappers.

    The sandbox harness starts a live Django server and Temporal worker that
    use separate DB connections. They must see committed rows immediately, so
    normal pytest-django test transactions do not work. ``transaction=True``
    makes the rows visible, but also puts every eval on the transactional test
    path, which flushes/re-initializes state between tests and defeats the
    long-lived eval database.

    Instead, ``_sandboxed_eval_database_access`` below creates the DB once and
    leaves access unblocked for the whole eval session. Strip accidental
    ``django_db`` markers so pytest-django does not add transactional fixtures
    back in.
    """
    base_dir = Path(__file__).parent
    for item in items:
        try:
            test_path = Path(str(item.fspath))
            test_path.relative_to(base_dir)
        except (TypeError, ValueError):
            continue
        node = item
        while node is not None:
            own_markers = getattr(node, "own_markers", None)
            if own_markers is not None:
                node.own_markers = [marker for marker in own_markers if marker.name != "django_db"]
            node = node.parent
        # NodeKeywords forbids __delitem__ in newer pytest — the own_markers
        # mutation above is what actually strips the marker; this pop is a
        # legacy belt-and-braces that's a no-op when not supported.
        try:
            item.keywords.pop("django_db", None)
        except (ValueError, TypeError):
            pass


@pytest.fixture(scope="session")
def django_db_setup(
    request: pytest.FixtureRequest,
    django_test_environment: None,
    django_db_blocker,
    django_db_use_migrations: bool,
    django_db_keepdb: bool,
    django_db_createdb: bool,
    django_db_modify_db_settings: None,
) -> Generator[None]:
    """Create the eval test DB even though eval items have no django_db marker."""
    from django.test.utils import setup_databases, teardown_databases

    from pytest_django.fixtures import _disable_migrations

    if not django_db_use_migrations:
        _disable_migrations()

    with django_db_blocker.unblock():
        db_cfg = setup_databases(
            verbosity=request.config.option.verbose,
            interactive=False,
            keepdb=django_db_keepdb and not django_db_createdb,
            aliases=SANDBOXED_EVAL_SETUP_DATABASES,
            serialized_aliases=set(),
        )

    yield

    if not django_db_keepdb:
        with django_db_blocker.unblock():
            teardown_databases(db_cfg, verbosity=request.config.option.verbose)


@pytest.fixture(scope="session", autouse=True)
def _sandboxed_eval_database_access(set_up_evals, django_db_blocker) -> Generator[None]:  # noqa: F811
    """Use one committed eval database instead of per-test transactions."""
    django_db_blocker.unblock()
    yield
    django_db_blocker.restore()


# Sandbox container name prefix used by the eval harness (set in SandboxConfig.name)
_EVAL_CONTAINER_PREFIX = "task-sandbox-"
_LONG_LIVED_SUBPROCESSES = LongLivedSubprocessManager()


def pytest_keyboard_interrupt(excinfo: object) -> None:  # noqa: ARG001
    _LONG_LIVED_SUBPROCESSES.stop_all()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:  # noqa: ARG001
    _LONG_LIVED_SUBPROCESSES.stop_all()


def _temporal_client_target(env: WorkflowEnvironment) -> tuple[str, str]:
    config = env.client.config()
    service_client = config["service_client"]
    target_host = service_client.config.target_host
    host, port = target_host.rsplit(":", maxsplit=1)
    return host, port


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
def _django_live_server(_sandboxed_eval_database_access):
    """Start an in-process Django HTTP server on the test database.

    Uses Django's ``LiveServerThread`` (same mechanism as pytest-django's
    ``live_server`` fixture, but session-scoped). The sandbox Docker container
    calls this server via ``host.docker.internal`` for API requests,
    log persistence, and the LLM gateway.

    Depends on ``_sandboxed_eval_database_access`` so the PostHog eval database
    setup has completed before any subprocess (LLM gateway, MCP) connects.
    """
    from pytest_django.live_server_helper import LiveServer

    # Bind on all interfaces so the sandbox Docker container can reach the server
    # via ``host.docker.internal`` (the docker bridge gateway). The socket binds
    # at thread start using this host; we then re-point ``thread.host`` at
    # localhost purely so ``server.url`` advertises a loopback address to
    # host-side clients (MCP server, LLM gateway) — the already-bound 0.0.0.0
    # socket still accepts both loopback and bridge connections.
    server = LiveServer(f"0.0.0.0:{DJANGO_LIVE_PORT}")
    server.thread.host = "127.0.0.1"
    logger.info("Django live server started at %s (bound on 0.0.0.0)", server.url)

    yield server

    server.stop()
    logger.info("Django live server stopped")


@pytest.fixture(scope="session", autouse=True)
def _sandboxed_local_skills(_sandbox_settings) -> Generator[Path]:
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
def _temporal_test_server() -> Generator[tuple[str, str, str]]:
    """Start an isolated Temporal dev server for sandboxed eval workflows."""
    loop = asyncio.new_event_loop()
    temporal_namespace = settings.TEMPORAL_NAMESPACE
    env: WorkflowEnvironment | None = None

    try:
        env = loop.run_until_complete(
            WorkflowEnvironment.start_local(
                namespace=temporal_namespace,
                ip="127.0.0.1",
                port=None,
                dev_server_log_level="warn",
            )
        )
        host, port = _temporal_client_target(env)
        logger.info("Sandboxed eval Temporal server ready at %s:%s namespace=%s", host, port, temporal_namespace)

        yield host, port, temporal_namespace
    finally:
        if env is not None:
            logger.info("Shutting down sandboxed eval Temporal server")
            loop.run_until_complete(env.shutdown())
        loop.close()


@pytest.fixture(scope="session", autouse=True)
def _sandbox_settings(
    _django_live_server: object,
    _llm_gateway: object,
    _temporal_test_server: tuple[str, str, str],
) -> Generator[None]:
    """Configure Django settings required by the sandbox/temporal activities.

    All URLs use ``host.docker.internal`` so they're reachable from inside
    Docker sandbox containers. Points at the in-process Django live server
    which shares the test database.

    Temporal is pointed at a per-session local dev server and task queue. That
    keeps eval workflows away from any dev worker already polling the normal
    tasks queue in the developer's environment.

    Also patches ``posthoganalytics.feature_enabled`` to return True for all
    flags so workflow guards pass.
    """
    from unittest.mock import patch

    from django.test import override_settings

    # Docker containers reach the host via host.docker.internal
    docker_api_url = f"http://host.docker.internal:{DJANGO_LIVE_PORT}"
    docker_llm_gateway_url = f"http://host.docker.internal:{LLM_GATEWAY_PORT}"
    temporal_host, temporal_port, temporal_namespace = _temporal_test_server
    temporal_task_queue = f"sandboxed-evals-tasks-{os.getpid()}"

    import posthoganalytics

    with (
        override_settings(
            DEBUG=True,  # Required for sandbox URL validation to allow http://localhost
            # The sandbox container reaches the Django live server with a
            # ``Host: host.docker.internal`` header; allow it (test-only) so the
            # agent's event-ingest stream isn't rejected with an invalid-host 400.
            ALLOWED_HOSTS=["*"],
            SANDBOX_PROVIDER="docker",
            SANDBOX_API_URL=docker_api_url,
            SANDBOX_LLM_GATEWAY_URL=docker_llm_gateway_url,
            SANDBOX_MCP_URL=f"http://host.docker.internal:{MCP_PORT}/mcp",
            TEMPORAL_HOST=temporal_host,
            TEMPORAL_PORT=temporal_port,
            TEMPORAL_NAMESPACE=temporal_namespace,
            TEMPORAL_CLIENT_CERT=None,
            TEMPORAL_CLIENT_KEY=None,
            TASKS_TASK_QUEUE=temporal_task_queue,
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
def _temporal_worker(_sandbox_settings, _terminate_stale_workflows, _sandboxed_eval_database_access):
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

    thread = threading.Thread(target=loop.run_until_complete, args=(_run(),), daemon=True)
    thread.start()

    if not ready_event.wait(timeout=30):
        pytest.fail(
            f"Temporal worker failed to start within 30s. "
            f"Is temporal running at {settings.TEMPORAL_HOST}:{settings.TEMPORAL_PORT}?"
        )

    logger.info("Eval temporal worker ready")
    yield

    loop.call_soon_threadsafe(stop_event.set)
    thread.join(timeout=10)


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
    _, stop = _LONG_LIVED_SUBPROCESSES.start(
        name="LLM gateway",
        port=LLM_GATEWAY_PORT,
        cmd=[
            str(uvicorn_bin),
            "llm_gateway.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(LLM_GATEWAY_PORT),
        ],
        cwd=gateway_dir,
        env=env,
        log_prefix="llm-gateway",
    )

    logger.info("LLM gateway ready on port %d", LLM_GATEWAY_PORT)
    yield

    stop()
    logger.info("LLM gateway stopped")


@pytest.fixture(scope="session", autouse=True)
def _mcp_server(_django_live_server, _sandbox_settings):
    """Start the MCP server as a subprocess for the eval session.

    Pointed at the in-process Django live server (which uses the test DB).
    Uses a non-default port to avoid conflicts with a running dev MCP server.

    Runs the Node-native Hono server via ``pnpm dev:hono``. In production the
    Cloudflare Worker is now a proxy that forwards to a regional Hono
    deployment, so Hono is what real users hit.
    """
    mcp_dir = Path(settings.BASE_DIR) / "services" / "mcp"
    if not (mcp_dir / "node_modules").exists():
        logger.info("Installing MCP server dependencies")
        subprocess.run(["pnpm", "install", "--frozen-lockfile"], cwd=mcp_dir, check=True, capture_output=True)

    api_url = str(_django_live_server)

    # The Hono server reads config directly from process env — no wrangler
    # --var wiring needed. PORT picks the listen port; the dev:hono script
    # bundles via esbuild then spawns Node on the bundle.
    env = {
        **os.environ,
        "POSTHOG_API_BASE_URL": api_url,
        "MCP_APPS_BASE_URL": f"http://localhost:{MCP_PORT}",
        "POSTHOG_MCP_APPS_ANALYTICS_BASE_URL": api_url,
        "NODE_ENV": "development",
        "PORT": str(MCP_PORT),
        "HOST": "0.0.0.0",
        # The MCP server evaluates feature flags via posthog-node, which is disabled
        # here (no POSTHOG_ANALYTICS_* config), so every flag would resolve false.
        # Force flag-gated behavior on for evals via the dev/test-only override seam
        # (honored only when NODE_ENV is explicitly development/test — set above).
        # `mcp-render-ui` gates the render_ui umbrella tool — see eval_render_ui.py.
        # `mcp-sql-schema-discovery` routes warehouse/system-table schema discovery
        # through `system.information_schema.*` SQL instead of read-data-warehouse-schema
        # — see eval_system_table_search.py.
        "FEATURE_FLAG_OVERRIDES": json.dumps({"mcp-render-ui": True, "mcp-sql-schema-discovery": True}),
    }

    logger.info("Starting MCP server (Hono runtime) on port %d (API: %s)", MCP_PORT, api_url)
    _, stop = _LONG_LIVED_SUBPROCESSES.start(
        name="MCP server",
        port=MCP_PORT,
        cmd=["pnpm", "dev:hono"],
        cwd=mcp_dir,
        env=env,
        log_prefix="mcp",
    )

    logger.info("MCP server ready on port %d", MCP_PORT)
    yield

    stop()
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
        from django.apps import apps

        CodeInvite = apps.get_model("tasks", "CodeInvite")
        CodeInviteRedemption = apps.get_model("tasks", "CodeInviteRedemption")

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


# Event-level properties the error-tracking ``searchQuery`` test cases match on
# (see ``products/error_tracking/backend/hogql_queries/error_tracking_query_runner_utils.py``).
# These are stored as JSON arrays (``["TypeError"]``); without materialized
# columns the bare ``properties.$exception_types`` lookup goes through
# ``JSONExtractString`` which returns ``""`` for non-string JSON values, so
# ``searchQuery`` filtering on these properties silently never matches anything.
# Materializing and backfilling once per session makes the sandbox behave like
# prod for error-tracking searchQuery, including reused local ClickHouse state
# where the columns already exist but older demo rows still need values.
_EVAL_MATERIALIZED_EVENT_PROPERTIES: tuple[str, ...] = (
    "$exception_types",
    "$exception_values",
)


def _ensure_event_search_columns_materialized(django_db_blocker) -> None:
    from ee.clickhouse.materialized_columns.columns import (
        backfill_materialized_columns,
        get_materialized_columns,
        materialize,
    )

    with django_db_blocker.unblock():
        existing_columns = get_materialized_columns("events")
        columns = []
        for property_name in _EVAL_MATERIALIZED_EVENT_PROPERTIES:
            column = existing_columns.get((property_name, "properties"))
            if column is None:
                column = materialize("events", property_name)
            columns.append(column)
        backfill_materialized_columns("events", columns, timedelta(days=180))


@pytest.fixture(scope="session", autouse=True)
def sandboxed_demo_data(
    set_up_evals,  # noqa: F811
    django_db_blocker,
    pytestconfig,
) -> SandboxedDemoData:
    """Seed the master Hedgebox team (once) and expose a per-case context factory."""
    from posthog.clickhouse.client import sync_execute

    master_team_id = ensure_master_demo_team(django_db_blocker)
    _ensure_event_search_columns_materialized(django_db_blocker)
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
