from datetime import UTC, date, datetime, time, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.warehouse_object_reads import SHARDED_WAREHOUSE_OBJECT_READS_DAILY_TABLE, ReadKind, SubjectKind

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery


def insert_rollup_row(team_id: int, subject_id: str, read_kind: ReadKind, read_at: datetime) -> None:
    sync_execute(
        f"""
        INSERT INTO {SHARDED_WAREHOUSE_OBJECT_READS_DAILY_TABLE}
            (team_id, day, read_kind, subject_kind, subject_id, max_event_time)
        VALUES
        """,
        [(team_id, read_at.date(), read_kind.value, SubjectKind.SAVED_QUERY.value, subject_id, read_at)],
    )


def noon(day: date) -> datetime:
    return datetime.combine(day, time(hour=12), tzinfo=UTC)


class TestSavedQueryLastRead(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.view = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="orders", query={"kind": "HogQLQuery", "query": "SELECT 1"}
        )

    def retrieve(self, **params: str) -> dict:
        response = self.client.get(f"/api/environments/{self.team.id}/warehouse_saved_queries/{self.view.id}/", params)
        self.assertEqual(response.status_code, 200, response.json())
        return response.json()

    def test_last_read_at_is_the_latest_read_of_this_view_in_this_team(self) -> None:
        today = date.today()
        latest_read = noon(today - timedelta(days=2))
        view_id = str(self.view.id)
        insert_rollup_row(self.team.id, view_id, ReadKind.READ, noon(today - timedelta(days=5)))
        insert_rollup_row(self.team.id, view_id, ReadKind.READ, latest_read)
        insert_rollup_row(self.team.id, view_id, ReadKind.REFRESH, noon(today - timedelta(days=1)))
        insert_rollup_row(self.team.id + 1, view_id, ReadKind.READ, noon(today - timedelta(days=1)))

        self.assertIsNone(self.retrieve()["last_read_at"])
        last_read_at = self.retrieve(include_last_read="true")["last_read_at"]
        self.assertEqual(datetime.fromisoformat(last_read_at), latest_read)

    def test_last_read_at_is_null_when_clickhouse_fails(self) -> None:
        with patch(
            "products.data_warehouse.backend.logic.saved_query_reads.sync_execute",
            side_effect=Exception("aux unavailable"),
        ):
            self.assertIsNone(self.retrieve(include_last_read="true")["last_read_at"])
