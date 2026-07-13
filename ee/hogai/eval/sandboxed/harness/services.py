from __future__ import annotations

import os
import json
import logging
import subprocess
from collections.abc import Callable
from pathlib import Path

from django.conf import settings
from django.db import connections

from products.tasks.backend.facade.agents import ENV_LOCAL_SKILLS_HOST_PATH, LocalSkillsCache

from ee.hogai.eval.sandboxed.long_lived_subprocess import LongLivedSubprocessManager, SubprocessStartupError

from .ports import LLM_GATEWAY_PORT, MCP_PORT

logger = logging.getLogger(__name__)

LONG_LIVED_SUBPROCESSES = LongLivedSubprocessManager()


def start_llm_gateway(live_server_url: str) -> Callable[[], None]:
    """Start the LLM gateway as a subprocess.

    Mirrors ``bin/start-llm-gateway``: runs uvicorn on a non-default port.
    The sandbox's agent-server uses this to proxy LLM calls to Anthropic.
    """
    gateway_dir = Path(settings.BASE_DIR) / "services" / "llm-gateway"
    venv_dir = gateway_dir / ".venv"
    uvicorn_bin = venv_dir / "bin" / "uvicorn"

    if not uvicorn_bin.exists():
        raise SubprocessStartupError(
            f"LLM gateway venv not found at {venv_dir}. "
            "Run `bin/start-llm-gateway` once or `cd services/llm-gateway && uv venv .venv && uv pip install -e .`"
        )
    # The LLM gateway uses pydantic BaseSettings with env_prefix="LLM_GATEWAY_".
    # DATABASE_URL and LLM_GATEWAY_ANTHROPIC_API_KEY come from the parent env
    # (e.g. .env.local / op run). We need to point it at the test database.
    conn = connections["default"]
    # The test DB setup rewrites settings_dict["NAME"] to the test DB name in
    # place, so don't re-prefix it.
    db_name = conn.settings_dict["NAME"]
    db_user = conn.settings_dict.get("USER", "posthog")
    db_password = conn.settings_dict.get("PASSWORD", "posthog")
    db_host = conn.settings_dict.get("HOST", "localhost")
    db_port = conn.settings_dict.get("PORT", "5432")
    test_db_url = f"postgres://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

    # No team rate-limit multiplier: the gateway keys multipliers by team id, but
    # each eval case runs as its own freshly minted team, so a mapping like {"1": 10}
    # never matches. Rate limits are per team, so every case gets the full base
    # budget (hundreds of requests/minute), which is already ample for eval traffic.
    env = {
        **os.environ,
        "UV_PROJECT_ENVIRONMENT": str(venv_dir),
        "LLM_GATEWAY_DATABASE_URL": test_db_url,
        "LLM_GATEWAY_DEBUG": "true",
        "LLM_GATEWAY_POSTHOG_HOST": live_server_url,
    }

    logger.info("Starting LLM gateway on port %d", LLM_GATEWAY_PORT)
    _, stop = LONG_LIVED_SUBPROCESSES.start(
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
    return stop


def start_mcp_server(live_server_url: str) -> Callable[[], None]:
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

    api_url = live_server_url

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
        # No flags currently need forcing on.
        "FEATURE_FLAG_OVERRIDES": json.dumps({}),
    }

    logger.info("Starting MCP server (Hono runtime) on port %d (API: %s)", MCP_PORT, api_url)
    _, stop = LONG_LIVED_SUBPROCESSES.start(
        name="MCP server",
        port=MCP_PORT,
        cmd=["pnpm", "dev:hono"],
        cwd=mcp_dir,
        env=env,
        log_prefix="mcp",
    )

    logger.info("MCP server ready on port %d", MCP_PORT)
    return stop


def build_local_skills(*, set_bind_mount_env: bool) -> Path:
    """Build local skills once per run and return the built dist dir.

    Uses a content-hash cache so repeat runs skip the build when nothing has
    changed, keeping the base image stable while letting eval authors iterate on
    skills without rebuilding it.

    Depends on ``DEBUG=True`` being active while the skill renderer runs — some
    template helpers (e.g. HogQL example rendering) guard on that setting. The
    harness sets ``DEBUG=1`` in the environment before ``django.setup()``, so
    that ordering holds by the time this runs.
    """
    cache = LocalSkillsCache()
    dist_dir = cache.ensure_built()
    if set_bind_mount_env:
        # Only ``DockerSandbox.create`` reads this to bind-mount the built skills.
        # Under the modal provider the locally built skills are instead baked into
        # the Modal image by the DEBUG ``from_dockerfile`` build, so setting it
        # there would be inert.
        os.environ[ENV_LOCAL_SKILLS_HOST_PATH] = str(dist_dir)
    return dist_dir


def stop_all_subprocesses() -> None:
    LONG_LIVED_SUBPROCESSES.stop_all()
