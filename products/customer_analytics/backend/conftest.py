from collections.abc import Iterator

import pytest

from posthog.clickhouse.client import sync_execute


def reset_membership_tables() -> None:
    sync_execute("TRUNCATE TABLE sharded_person_group_membership")
    sync_execute("TRUNCATE TABLE person_group_membership_config")


@pytest.fixture
def membership_cleanup_tables(django_db_setup: None) -> Iterator[None]:
    # Team discovery scans all teams, so unique test team IDs do not isolate these tables.
    reset_membership_tables()
    try:
        yield
    finally:
        reset_membership_tables()
