import json

from posthog.test.base import ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_log_archive import QUERY_LOG_ARCHIVE_OPS_TABLE_SQL

TABLE = "test_query_log_archive_aliases"


class TestQueryLogArchiveCostPlannerAliases(ClickhouseTestMixin, SimpleTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        sync_execute(f"DROP TABLE IF EXISTS {TABLE} SYNC")
        sync_execute(
            QUERY_LOG_ARCHIVE_OPS_TABLE_SQL(table_name=TABLE, engine="MergeTree", include_table_clauses=False)
            + " ORDER BY (team_id, event_date)"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            sync_execute(f"DROP TABLE IF EXISTS {TABLE} SYNC")
        finally:
            super().tearDownClass()

    def _insert(self, query_id: str, log_comment: dict) -> None:
        sync_execute(
            f"INSERT INTO {TABLE} (query_id, type, event_date, event_time, team_id, log_comment) "
            "VALUES (%(query_id)s, 'QueryFinish', today(), now(), %(team_id)s, %(log_comment)s)",
            {"query_id": query_id, "team_id": log_comment["team_id"], "log_comment": json.dumps(log_comment)},
        )

    def _read(self, query_id: str) -> tuple[str, int, int]:
        [row] = sync_execute(
            f"SELECT lc_plan_fingerprint, lc_estimated_rows, lc_estimated_bytes FROM {TABLE} WHERE query_id = %(q)s",
            {"q": query_id},
        )
        return row

    @parameterized.expand(
        [
            (
                "present",
                {
                    "team_id": 1,
                    "plan_fingerprint": "e8ff93df7e4e989a",
                    "estimated_rows": 1_800_000,
                    "estimated_bytes": 9_000,
                },
                ("e8ff93df7e4e989a", 1_800_000, 9_000),
            ),
            ("absent", {"team_id": 1, "query_type": "HogQLQuery"}, ("", 0, 0)),
            (
                "large_int_stays_int64",
                {"team_id": 1, "plan_fingerprint": "ab", "estimated_rows": 1_800_000_000_000, "estimated_bytes": 0},
                ("ab", 1_800_000_000_000, 0),
            ),
        ]
    )
    def test_aliases_read_the_tag_values_back(self, name, log_comment, expected):
        self._insert(name, log_comment)

        assert self._read(name) == expected
