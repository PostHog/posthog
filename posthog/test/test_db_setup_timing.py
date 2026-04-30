"""Sentinel test that exposes the cost of pytest's database setup.

Without this, Django migrations + ClickHouse table creation + sqlx persons
migrations all run inside the *first* collected test's setup phase, making
that test look mysteriously slow in `--durations` output.

`pytest_collection_modifyitems` in `posthog/conftest.py` reorders this test
to run first, so its setup phase consistently captures the db-setup cost.
Per-migration timings are also printed at the end of the run.
"""

import pytest


@pytest.mark.db_setup_timing
@pytest.mark.django_db
def test_django_db_setup_timing() -> None:
    pass
