"""Smoke test for the sandboxed eval harness.

Validates that the harness infrastructure boots cleanly and that MCP + the
LLM Gateway are reachable from inside a docker container via
``host.docker.internal`` — the exact network path a real task sandbox uses
(see ``products/tasks/backend/services/docker_sandbox.py``, where the
provider adds ``--add-host host.docker.internal:host-gateway`` and rewrites
``localhost``/``127.0.0.1`` URLs to ``host.docker.internal``).

Intentionally does NOT run any agent eval case — no LLM calls, no Braintrust,
no Anthropic/PostHog API keys. The smoke test file is named ``test_*.py``
(not ``eval_*.py``) so the Braintrust eval helpers ignore it and it's picked
up by default pytest collection.

Run locally with:

    pytest ee/hogai/eval/sandboxed/ci/test_harness_smoke.py -vv

All heavy bootstrap (Django live server, temporal worker, LLM gateway
subprocess, MCP subprocess, sandbox container cleanup) is handled by the
session-scoped autouse fixtures in ``ee/hogai/eval/sandboxed/conftest.py``.
"""

from __future__ import annotations

import socket
import subprocess

import pytest

from ee.hogai.eval.sandboxed.conftest import LLM_GATEWAY_PORT, MCP_PORT

# Pinned so a silent upstream tag move can't cause flaky CI.
_CURL_IMAGE = "curlimages/curl:8.10.1"


def _assert_listening(port: int) -> None:
    """Fail fast with a clear message if the host-side service isn't even up."""
    try:
        sock = socket.create_connection(("localhost", port), timeout=5)
    except OSError as exc:
        pytest.fail(f"host-side service on localhost:{port} is not accepting connections: {exc}")
    else:
        sock.close()


def _curl_from_docker(url: str) -> subprocess.CompletedProcess:
    """Run curl inside a short-lived container with the same host-gateway bridge the real sandbox uses.

    Prints the HTTP status to stdout (via ``-w %{http_code}``) and exits
    non-zero on HTTP errors (``-f``). 10s per-request timeout keeps a broken
    network path from hanging CI.
    """
    return subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--add-host",
            "host.docker.internal:host-gateway",
            _CURL_IMAGE,
            "-fsS",
            "-m",
            "10",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            url,
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )


def _assert_reachable_from_docker(url: str, service: str) -> None:
    result = _curl_from_docker(url)
    if result.returncode != 0:
        pytest.fail(
            f"{service} not reachable from a docker container at {url}\n"
            f"  returncode={result.returncode}\n"
            f"  stdout={result.stdout!r}\n"
            f"  stderr={result.stderr!r}"
        )
    status = result.stdout.strip()
    # Any 2xx/3xx means the service is live on the bridge. 4xx/5xx bubble up
    # via -f as a non-zero returncode already, so we'd have failed above.
    if not (status.startswith("2") or status.startswith("3")):
        pytest.fail(f"{service} returned unexpected HTTP status {status!r} from docker at {url}")


@pytest.mark.django_db
def test_llm_gateway_reachable_from_docker():
    """LLM Gateway must answer on ``host.docker.internal`` from inside a docker container.

    The landing path ``/`` is mounted by ``llm_gateway.api.health.health_router``
    at module root (see ``services/llm-gateway/src/llm_gateway/api/health.py``)
    and does not hit the DB or Anthropic, so it's a safe reachability probe.
    """
    _assert_listening(LLM_GATEWAY_PORT)
    _assert_reachable_from_docker(f"http://host.docker.internal:{LLM_GATEWAY_PORT}/", "LLM gateway")


@pytest.mark.django_db
def test_mcp_server_reachable_from_docker():
    """MCP server must answer on ``host.docker.internal`` from inside a docker container.

    The wrangler dev server returns a static landing page at ``/`` (see
    ``services/mcp/src/index.ts``), so we probe that instead of ``/mcp``
    which requires OAuth.
    """
    _assert_listening(MCP_PORT)
    _assert_reachable_from_docker(f"http://host.docker.internal:{MCP_PORT}/", "MCP server")
