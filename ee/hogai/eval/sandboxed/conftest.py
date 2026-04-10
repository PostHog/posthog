from __future__ import annotations

import os
import time
import socket
import asyncio
import logging
import threading
import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest

from django.conf import settings

from posthog.models import Organization, Team, User
from posthog.temporal.common.worker import create_worker

from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext
from products.tasks.backend.temporal import (
    ACTIVITIES as TASKS_ACTIVITIES,
    WORKFLOWS as TASKS_WORKFLOWS,
)

# We want the PostHog set_up_evals fixture here
from ee.hogai.eval.conftest import set_up_evals  # noqa: F401
from ee.hogai.eval.data_setup import create_core_memory, create_isolated_demo_data
from ee.models.assistant import CoreMemory

logger = logging.getLogger(__name__)

MCP_PORT = 18787  # Non-default port to avoid conflicts with dev MCP
DJANGO_LIVE_PORT = 18000  # Non-default port for in-process Django server
LLM_GATEWAY_PORT = 13308  # Non-default port to avoid conflicts with dev LLM gateway

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


# TODO: Re-enable once eval harness is stable
# atexit.register(_cleanup_eval_containers)


# ---------------------------------------------------------------------------
# Django live server (in-process, shares test DB)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _django_live_server(django_db_blocker):
    """Start an in-process Django HTTP server on the test database.

    Uses Django's ``LiveServerThread`` (same mechanism as pytest-django's
    ``live_server`` fixture, but session-scoped). The sandbox Docker container
    calls this server via ``host.docker.internal`` for API requests,
    log persistence, and the LLM gateway.
    """
    from pytest_django.live_server_helper import LiveServer

    django_db_blocker.unblock()

    server = LiveServer(f"localhost:{DJANGO_LIVE_PORT}")
    logger.info("Django live server started at %s", server.url)

    yield server

    server.stop()
    django_db_blocker.restore()
    logger.info("Django live server stopped")


# ---------------------------------------------------------------------------
# Sandbox settings
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Temporal worker (in-process, same DB as test)
# ---------------------------------------------------------------------------


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
            activities=TASKS_ACTIVITIES,
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


# ---------------------------------------------------------------------------
# LLM gateway (subprocess)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _llm_gateway(_django_live_server):
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
    # conn.settings_dict["NAME"] has the original DB name; the actual test DB
    # name is available on the connection wrapper after the test runner creates it.
    db_name = conn.settings_dict.get("TEST", {}).get("NAME") or f"test_{conn.settings_dict['NAME']}"
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

    logger.info("Starting LLM gateway on port %d (DB: %s)", LLM_GATEWAY_PORT, test_db_url)
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


# ---------------------------------------------------------------------------
# MCP server (subprocess, pointed at in-process Django server)
# ---------------------------------------------------------------------------


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

    logger.info("Starting MCP server on port %d (API: %s)", MCP_PORT, api_url)
    proc = subprocess.Popen(
        ["pnpm", "wrangler", "dev", "--port", str(MCP_PORT)],
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


# ---------------------------------------------------------------------------
# Demo data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def demo_org_team_user(
    set_up_evals,  # noqa: F811
    django_db_blocker,
) -> Generator[tuple[Organization, Team, User], None, None]:
    yield create_isolated_demo_data(django_db_blocker, label="sandboxed")


@pytest.fixture(scope="session", autouse=True)
def core_memory(demo_org_team_user, django_db_blocker) -> Generator[CoreMemory, None, None]:
    yield create_core_memory(demo_org_team_user[1], django_db_blocker)


@pytest.fixture(scope="session", autouse=True)
def _tasks_access(demo_org_team_user, django_db_blocker):
    """Grant the eval user access to the tasks API.

    Creates a ``CodeInviteRedemption`` so that ``TasksAccessPermission`` passes
    without relying on the ``tasks`` feature flag (which requires a mock that
    doesn't survive across threads reliably).
    """
    from products.tasks.backend.models import CodeInvite, CodeInviteRedemption

    org, _team, user = demo_org_team_user
    with django_db_blocker.unblock():
        invite, _ = CodeInvite.objects.get_or_create(code="eval-harness", max_redemptions=0, is_active=True)
        CodeInviteRedemption.objects.get_or_create(invite_code=invite, user=user, organization=org)


@pytest.fixture(scope="session")
def sandbox_context(demo_org_team_user) -> CustomPromptSandboxContext:
    """Build a sandbox context for the eval harness using the demo team/user."""
    _org, team, user = demo_org_team_user
    return CustomPromptSandboxContext(team_id=team.id, user_id=user.id)
