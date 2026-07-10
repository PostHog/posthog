from __future__ import annotations

import os
import shutil
import logging
import subprocess
from abc import ABC, abstractmethod
from contextlib import ExitStack
from pathlib import Path
from typing import Any, ClassVar, Literal

from .ports import DJANGO_LIVE_PORT, LLM_GATEWAY_PORT, MCP_PORT
from .tunnels import NgrokTunnels, resolve_authtoken

logger = logging.getLogger(__name__)

SandboxProvider = Literal["docker", "modal"]

SANDBOX_PROVIDER_SETTING: dict[SandboxProvider, str] = {
    "docker": "docker",
    "modal": "MODAL_DOCKER",
}
"""Value each provider writes to ``settings.SANDBOX_PROVIDER``, which selects the
sandbox class in ``products.tasks``. ``modal`` maps to ``MODAL_DOCKER``: a
``ModalSandbox`` subclass pinned to a dedicated Modal app.

``__main__`` sets this in the environment before ``django.setup()``. It must be
correct before the *first* ``Sandbox`` access, because ``products.tasks`` resolves
that class once and caches it in module globals; a later ``override_settings`` can
no longer change it. ``.env`` ships ``SANDBOX_PROVIDER=docker``, so without the
early set a modal run would cache ``DockerSandbox`` and silently execute locally."""

EVAL_CONTAINER_PREFIX = "task-sandbox-"
"""Container name prefix the sandbox harness stamps on every eval container
(see ``SandboxConfig.name`` / ``get_sandbox_name_for_task``)."""

SETUP_GUIDE = "docs/internal/sandboxes-setup-guide.md"


class PreflightError(RuntimeError):
    """A provider prerequisite is missing. Raised before any infrastructure boots."""


def cleanup_eval_containers() -> None:
    """Force-remove every leftover eval sandbox container.

    Best effort — also runs from an ``atexit`` hook, where a raised exception
    would obscure whatever actually killed the run.
    """
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={EVAL_CONTAINER_PREFIX}", "--format", "{{.ID}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for container_id in result.stdout.strip().splitlines():
            if container_id:
                logger.info("Cleaning up eval container %s", container_id)
                subprocess.run(["docker", "rm", "-f", container_id], capture_output=True, timeout=10)
    except Exception:
        pass


class SandboxProviderStrategy(ABC):
    """Per-provider bootstrap, settings, and teardown for a harness run."""

    name: ClassVar[SandboxProvider]

    default_max_sandboxes: ClassVar[int | None]
    """``None`` means unbounded — every case may hold a sandbox at once."""

    @abstractmethod
    def preflight(self) -> None:
        """Fail fast when a prerequisite is missing, before anything is started."""

    def start(self, stack: ExitStack) -> None:  # noqa: B027 — optional hook; docker brings up nothing of its own
        """Bring up provider-owned infrastructure, registering teardown on ``stack``."""

    @abstractmethod
    def settings_overrides(self) -> dict[str, Any]:
        """Django settings the sandbox and its temporal activities read."""

    def sandbox_timeout_seconds(self, per_case_timeout_seconds: int) -> int | None:
        """Per-sandbox max lifetime, or ``None`` to keep ``SANDBOX_TTL_SECONDS``."""
        return None

    def cleanup(self) -> None:  # noqa: B027 — optional hook; modal has nothing to sweep host-side
        """End-of-run sweep for anything per-case teardown may have missed."""


class DockerProviderStrategy(SandboxProviderStrategy):
    """Local Docker sandboxes. Each container defaults to 16 GB, so host RAM,
    not the sandbox API, is what bounds concurrency."""

    name: ClassVar[SandboxProvider] = "docker"
    default_max_sandboxes: ClassVar[int | None] = 4

    def __init__(self, *, keep_containers: bool = False) -> None:
        self.keep_containers = keep_containers

    def preflight(self) -> None:
        if shutil.which("docker") is None:
            raise PreflightError("`docker` not found on PATH. The docker provider needs a local Docker daemon.")
        try:
            result = subprocess.run(["docker", "info"], capture_output=True, timeout=20)
        except Exception as e:
            raise PreflightError(f"Could not reach the Docker daemon: {e}") from e
        if result.returncode != 0:
            raise PreflightError("The Docker daemon is not reachable. Start Docker and retry.")

    def settings_overrides(self) -> dict[str, Any]:
        # Docker containers reach the host via host.docker.internal.
        return {
            "SANDBOX_PROVIDER": SANDBOX_PROVIDER_SETTING[self.name],
            "SANDBOX_API_URL": f"http://host.docker.internal:{DJANGO_LIVE_PORT}",
            "SANDBOX_LLM_GATEWAY_URL": f"http://host.docker.internal:{LLM_GATEWAY_PORT}",
            "SANDBOX_MCP_URL": f"http://host.docker.internal:{MCP_PORT}/mcp",
        }

    def cleanup(self) -> None:
        if self.keep_containers:
            logger.info("--keep-sandbox-containers set, skipping container cleanup")
            return
        cleanup_eval_containers()


class ModalProviderStrategy(SandboxProviderStrategy):
    """Remote Modal sandboxes, reached from Modal's network through ngrok tunnels.

    Runs under the ``MODAL_DOCKER`` provider — the same ``ModalSandbox`` class
    against a dedicated Modal app, so the DEBUG-mode local image builds (which
    bake the freshly built local skills into the image) don't pollute the
    production app's image cache.
    """

    name: ClassVar[SandboxProvider] = "modal"
    default_max_sandboxes: ClassVar[int | None] = None

    def __init__(self) -> None:
        self._tunnels: NgrokTunnels | None = None

    def preflight(self) -> None:
        if shutil.which("ngrok") is None:
            raise PreflightError(
                "`ngrok` not found on PATH. Modal sandboxes run outside this host, so the "
                f"Django API, LLM gateway, and MCP server must be publicly reachable. See {SETUP_GUIDE}."
            )
        if resolve_authtoken() is None:
            # Three simultaneous tunnels need a paid, authenticated agent. Without a
            # token ngrok starts and then fails per-tunnel, which would otherwise
            # surface only as a 60s startup timeout.
            raise PreflightError(
                "No ngrok authtoken found. Set NGROK_AUTHTOKEN, or run `ngrok config add-authtoken <token>` "
                f"with a token from https://dashboard.ngrok.com/get-started/your-authtoken. See {SETUP_GUIDE}."
            )
        has_env_tokens = bool(os.environ.get("MODAL_TOKEN_ID") and os.environ.get("MODAL_TOKEN_SECRET"))
        if not has_env_tokens and not (Path.home() / ".modal.toml").exists():
            raise PreflightError(
                "No Modal credentials found. Set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET, "
                f"or run `modal token new`. See {SETUP_GUIDE}."
            )
        if not os.environ.get("SANDBOX_JWT_PRIVATE_KEY"):
            # Sandbox provisioning derives the sandbox's public key from this and raises without it.
            raise PreflightError(
                "SANDBOX_JWT_PRIVATE_KEY is unset. The dev key ships in .env.example — "
                "source your .env (`set -a; source .env; set +a`) before running the harness."
            )

    def start(self, stack: ExitStack) -> None:
        tunnels = NgrokTunnels(
            {
                "django": DJANGO_LIVE_PORT,
                "gateway": LLM_GATEWAY_PORT,
                "mcp": MCP_PORT,
            }
        )
        tunnels.start()
        stack.callback(tunnels.stop)
        self._tunnels = tunnels

    def settings_overrides(self) -> dict[str, Any]:
        if self._tunnels is None:
            raise RuntimeError("ModalProviderStrategy.start() must run before settings_overrides()")
        return {
            "SANDBOX_PROVIDER": SANDBOX_PROVIDER_SETTING[self.name],
            "SANDBOX_API_URL": self._tunnels.url_for("django"),
            "SANDBOX_LLM_GATEWAY_URL": self._tunnels.url_for("gateway"),
            "SANDBOX_MCP_URL": f"{self._tunnels.url_for('mcp')}/mcp",
        }

    def sandbox_timeout_seconds(self, per_case_timeout_seconds: int) -> int | None:
        # Under TEST=1, SANDBOX_TTL_SECONDS equals the per-case timeout, so Modal
        # would reap a slow case's sandbox exactly as it was about to finish.
        return per_case_timeout_seconds + 10 * 60


def build_provider(provider: SandboxProvider, *, keep_containers: bool) -> SandboxProviderStrategy:
    if provider == "docker":
        return DockerProviderStrategy(keep_containers=keep_containers)
    return ModalProviderStrategy()
