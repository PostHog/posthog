from datetime import datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.distinct_id_usage.sql import TABLE_BASE_NAME, TRUNCATE_DISTINCT_ID_USAGE_TABLE_SQL


class TestDistinctIdUsageAggregation(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        sync_execute(TRUNCATE_DISTINCT_ID_USAGE_TABLE_SQL())

    def _insert_into_distinct_id_usage(self, team_id: int, distinct_id: str, minute: datetime, count: int = 1):
        """Directly insert into the table for testing (bypassing MV)"""
        sync_execute(
            f"""
            INSERT INTO {TABLE_BASE_NAME} (team_id, distinct_id, minute, event_count)
            VALUES (%(team_id)s, %(distinct_id)s, %(minute)s, %(count)s)
            """,
            {"team_id": team_id, "distinct_id": distinct_id, "minute": minute, "count": count},
        )

    def _query_distinct_id_usage(self, team_id: int, minutes_ago: int = 60):
        """Query the table to get aggregated counts"""
        result = sync_execute(
            f"""
            SELECT distinct_id, sum(event_count) as total
            FROM {TABLE_BASE_NAME}
            WHERE team_id = %(team_id)s
              AND minute >= now() - INTERVAL %(minutes)s MINUTE
            GROUP BY distinct_id
            ORDER BY total DESC
            """,
            {"team_id": team_id, "minutes": minutes_ago},
        )
        return {row[0]: row[1] for row in result}

    def test_aggregates_events_by_distinct_id(self):
        now = datetime.now().replace(second=0, microsecond=0)

        # Insert multiple events for same distinct_id in same minute
        self._insert_into_distinct_id_usage(self.team.pk, "user_1", now, count=5)
        self._insert_into_distinct_id_usage(self.team.pk, "user_1", now, count=3)
        self._insert_into_distinct_id_usage(self.team.pk, "user_2", now, count=2)

        result = self._query_distinct_id_usage(self.team.pk)

        # SummingMergeTree should sum the counts
        self.assertEqual(result["user_1"], 8)
        self.assertEqual(result["user_2"], 2)

    def test_separates_by_team_id(self):
        now = datetime.now().replace(second=0, microsecond=0)

        self._insert_into_distinct_id_usage(self.team.pk, "shared_user", now, count=10)
        self._insert_into_distinct_id_usage(99999, "shared_user", now, count=5)

        result = self._query_distinct_id_usage(self.team.pk)

        # Should only see this team's data
        self.assertEqual(result["shared_user"], 10)

    def test_separates_by_minute(self):
        now = datetime.now().replace(second=0, microsecond=0)
        one_minute_ago = now - timedelta(minutes=1)

        self._insert_into_distinct_id_usage(self.team.pk, "user_1", now, count=5)
        self._insert_into_distinct_id_usage(self.team.pk, "user_1", one_minute_ago, count=3)

        result = self._query_distinct_id_usage(self.team.pk)

        # Both minutes should be summed in the query
        self.assertEqual(result["user_1"], 8)

    def test_can_find_high_volume_distinct_ids(self):
        now = datetime.now().replace(second=0, microsecond=0)

        # Simulate a misused distinct_id with high volume
        self._insert_into_distinct_id_usage(self.team.pk, "test_label", now, count=10000)
        self._insert_into_distinct_id_usage(self.team.pk, "normal_user_1", now, count=50)
        self._insert_into_distinct_id_usage(self.team.pk, "normal_user_2", now, count=30)

        # Query for high-volume distinct_ids
        result = sync_execute(
            f"""
            SELECT distinct_id, sum(event_count) as total
            FROM {TABLE_BASE_NAME}
            WHERE team_id = %(team_id)s
              AND minute >= now() - INTERVAL 60 MINUTE
            GROUP BY distinct_id
            HAVING total > 1000
            ORDER BY total DESC
            """,
            {"team_id": self.team.pk},
        )

        # Should only find the abusive distinct_id
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], "test_label")
        self.assertEqual(result[0][1], 10000)

    def test_can_count_unique_distinct_ids_per_team(self):
        now = datetime.now().replace(second=0, microsecond=0)

        # Insert events for multiple distinct_ids
        for i in range(100):
            self._insert_into_distinct_id_usage(self.team.pk, f"user_{i}", now, count=1)

        # Count unique distinct_ids
        result = sync_execute(
            f"""
            SELECT count(DISTINCT distinct_id)
            FROM {TABLE_BASE_NAME}
            WHERE team_id = %(team_id)s
              AND minute >= now() - INTERVAL 60 MINUTE
            """,
            {"team_id": self.team.pk},
        )

        self.assertEqual(result[0][0], 100)

    def test_materialized_view_populates_from_events(self):
        """Integration test: verify the MV correctly populates distinct_id_usage from sharded_events"""
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="mv_test_user",
        )
        flush_persons_and_events()

        result = sync_execute(
            f"""
            SELECT distinct_id, sum(event_count) as total
            FROM {TABLE_BASE_NAME}
            WHERE team_id = %(team_id)s AND distinct_id = 'mv_test_user'
            GROUP BY distinct_id
            """,
            {"team_id": self.team.pk},
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], "mv_test_user")
        self.assertEqual(result[0][1], 1)
