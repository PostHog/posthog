import socket
import asyncio

import pytest

import requests

from posthog.asgi import application

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
    server.install_signal_handlers = lambda: None  # type: ignore[assignment]

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
