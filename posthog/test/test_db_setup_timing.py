"""Sentinel test that exposes the cost of pytest's database setup.

Without this, Django migrations + ClickHouse table creation + sqlx persons
migrations all run inside the *first* collected test's setup phase, making
that test look mysteriously slow in `--durations` output.

Opt in by setting `POSTHOG_DB_SETUP_TIMING=1`. When set, `posthog/conftest.py`
reorders this test to run first, so its setup phase consistently captures the
db-setup cost. Per-migration timings are also printed at the end of the run.

The test is skipped by default so it never forces a database to be set up
just for the sake of timing it.
"""

import os

import pytest


@pytest.mark.skipif(
    os.environ.get("POSTHOG_DB_SETUP_TIMING", "").lower() not in {"1", "true", "yes"},
    reason="Set POSTHOG_DB_SETUP_TIMING=1 to enable database setup timing instrumentation.",
)
@pytest.mark.db_setup_timing
@pytest.mark.django_db
def test_django_db_setup_timing() -> None:
    pass
