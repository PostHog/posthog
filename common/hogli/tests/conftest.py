"""Shared test fixtures for hogli tests."""

import os

import pytest

from hogli import telemetry

# Must be set before any Django-related imports during test collection
os.environ["DJANGO_SKIP_MIGRATIONS"] = "true"


@pytest.fixture(autouse=True)
def _clear_pending_threads():
    telemetry._pending_threads.clear()
    yield
    telemetry._pending_threads.clear()
