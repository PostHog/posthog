import socket
import asyncio

import pytest
from unittest import mock

from django.test import override_settings

import requests

from posthog.asgi import application

from products.warehouse_sources.backend.facade.source_management import SourceRegistry

uvicorn = pytest.importorskip("uvicorn")


async def _wait_for_server_started(server) -> None:
    while not server.started:
        await asyncio.sleep(0.05)


def _get_available_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_uvicorn_boots_posthog_application_under_django_5() -> None:
    """Test that PostHog ASGI application properly handles Django 5 lifespan events."""
    port = _get_available_port()

    config = uvicorn.Config(
        application,
        host="127.0.0.1",
        port=port,
        lifespan="on",  # This enables lifespan events that Django 5 sends
        log_level="error",
        loop="asyncio",
    )
    server = uvicorn.Server(config)

    # Running inside pytest means signal handlers are managed by the test process.
    server.install_signal_handlers = lambda: None

    serve_task = asyncio.create_task(server.serve())

    try:
        # Wait for server to start - this includes processing lifespan.startup
        await asyncio.wait_for(_wait_for_server_started(server), timeout=10)

        # Verify the server actually started successfully (lifespan.startup was handled)
        assert server.started, "Server should have started successfully after handling lifespan.startup"

        # Test that HTTP requests work normally
        response = await asyncio.to_thread(requests.get, f"http://127.0.0.1:{port}/_health/")
        assert response.status_code in {200, 503}, f"Health check failed with status {response.status_code}"

    finally:
        # This will trigger lifespan.shutdown event
        server.should_exit = True

        # Wait for graceful shutdown - this tests lifespan.shutdown handling
        try:
            await asyncio.wait_for(serve_task, timeout=5)
        except TimeoutError:
            pytest.fail("Server failed to shutdown gracefully - lifespan.shutdown may not be handled properly")


@pytest.mark.asyncio
async def test_lifespan_events_handled_directly() -> None:
    """Test lifespan events are handled correctly by the ASGI application directly."""
    startup_completed = False
    shutdown_completed = False

    async def mock_receive():
        # Simulate lifespan.startup event
        if not startup_completed:
            return {"type": "lifespan.startup"}
        else:
            # Simulate lifespan.shutdown event
            return {"type": "lifespan.shutdown"}

    async def mock_send(message):
        nonlocal startup_completed, shutdown_completed
        if message["type"] == "lifespan.startup.complete":
            startup_completed = True
        elif message["type"] == "lifespan.shutdown.complete":
            shutdown_completed = True

    # Test lifespan scope handling
    scope = {"type": "lifespan"}

    # This should handle startup
    task = asyncio.create_task(application(scope, mock_receive, mock_send))

    # Give it a moment to process startup
    await asyncio.sleep(0.1)
    assert startup_completed, "lifespan.startup should have been completed"

    # Give it a moment to process shutdown and complete
    await asyncio.sleep(0.1)
    await task
    assert shutdown_completed, "lifespan.shutdown should have been completed"


class _LifespanDriver:
    # Feeds the application queued server messages and records what it sends back.
    def __init__(self, messages: list[dict]) -> None:
        self.sent: list[dict] = []
        self._incoming: asyncio.Queue[dict] = asyncio.Queue()
        for message in messages:
            self._incoming.put_nowait(message)

    async def _receive(self) -> dict:
        return await self._incoming.get()

    async def _send(self, message: dict) -> None:
        self.sent.append(message)

    async def run(self) -> None:
        # A hang here means the application kept waiting for messages it should not expect.
        await asyncio.wait_for(application({"type": "lifespan"}, self._receive, self._send), timeout=5)


@pytest.mark.asyncio
async def test_lifespan_startup_skips_source_registry_prewarm_when_disabled() -> None:
    driver = _LifespanDriver([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

    with override_settings(PREWARM_WAREHOUSE_SOURCE_REGISTRY=False):
        with mock.patch.object(SourceRegistry, "get_all_sources") as mock_load:
            await driver.run()

    mock_load.assert_not_called()
    assert driver.sent == [{"type": "lifespan.startup.complete"}, {"type": "lifespan.shutdown.complete"}]


@pytest.mark.asyncio
async def test_lifespan_startup_schedules_web_bot_auth_key_validation() -> None:
    driver = _LifespanDriver([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

    with override_settings(WEB_BOT_AUTH_PRIVATE_KEYS_ENV_VAR_PRESENT=True):
        with mock.patch(
            "posthog.web_bot_auth_keys.validate_configured_web_bot_auth_private_keys_in_background"
        ) as validate_keys:
            await driver.run()

    validate_keys.assert_called_once_with()
    assert driver.sent == [{"type": "lifespan.startup.complete"}, {"type": "lifespan.shutdown.complete"}]


@pytest.mark.asyncio
async def test_lifespan_startup_prewarms_source_registry_before_reporting_ready() -> None:
    driver = _LifespanDriver([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])
    sent_when_load_ran: list[dict] | None = None

    def record_send_state() -> dict:
        nonlocal sent_when_load_ran
        sent_when_load_ran = list(driver.sent)
        return {}

    with override_settings(PREWARM_WAREHOUSE_SOURCE_REGISTRY=True):
        with mock.patch.object(SourceRegistry, "get_all_sources", side_effect=record_send_state) as mock_load:
            await driver.run()

    assert mock_load.call_count == 1
    # Nothing had been sent when the load ran: it finished before lifespan.startup.complete.
    assert sent_when_load_ran == []
    assert driver.sent == [{"type": "lifespan.startup.complete"}, {"type": "lifespan.shutdown.complete"}]


@pytest.mark.asyncio
async def test_lifespan_startup_prewarm_failure_still_reports_startup_complete() -> None:
    driver = _LifespanDriver([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

    with override_settings(PREWARM_WAREHOUSE_SOURCE_REGISTRY=True):
        with mock.patch.object(SourceRegistry, "get_all_sources", side_effect=RuntimeError("catalog broke")):
            await driver.run()

    # A broken catalog must not fail worker startup (respawn loops); the worker serves
    # cold and the registry's lazy loading retries on first use.
    assert driver.sent == [{"type": "lifespan.startup.complete"}, {"type": "lifespan.shutdown.complete"}]
