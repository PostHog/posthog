import socket
import asyncio

import pytest

import django

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
async def test_uvicorn_boots_posthog_application_under_django_5() -> None:
    if django.VERSION < (5, 0):
        pytest.skip("Test only runs against Django 5 to validate lifespan support")

    port = _get_available_port()

    config = uvicorn.Config(
        application,
        host="127.0.0.1",
        port=port,
        lifespan="on",
        log_level="error",
        loop="asyncio",
    )
    server = uvicorn.Server(config)

    # Running inside pytest means signal handlers are managed by the test process.
    server.install_signal_handlers = lambda: None  # type: ignore[assignment]

    serve_task = asyncio.create_task(server.serve())

    try:
        await asyncio.wait_for(_wait_for_server_started(server), timeout=10)

        response = await asyncio.to_thread(requests.get, f"http://127.0.0.1:{port}/_health/")
        assert response.status_code in {200, 503}
    finally:
        server.should_exit = True
        await serve_task
