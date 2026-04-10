"""Shared test fixtures for hogli tests."""

import os

import pytest

from hogli import telemetry

# Must be set before any Django-related imports during test collection
os.environ["DJANGO_SKIP_MIGRATIONS"] = "true"


@pytest.fixture(autouse=True)
def _clear_telemetry_queue():
    with telemetry._client._lock:
        telemetry._client._queue.clear()
    yield
    with telemetry._client._lock:
        telemetry._client._queue.clear()
