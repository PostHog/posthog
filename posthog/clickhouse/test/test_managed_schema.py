import pytest

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.managed_schema import ClickHouseDatabase


@pytest.mark.django_db
def test_new_process_rebuilds_schema_after_fixture_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    database = ClickHouseDatabase()
    database.restore()
    sync_execute("DROP TABLE trace_spans")
    monkeypatch.setattr(ClickHouseDatabase, "_snapshot", {})
    database.create_test_tables(kafka=False)

    assert sync_execute("SELECT count() FROM exchange_rate")[0][0] > 0
