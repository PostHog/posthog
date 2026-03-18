import uuid
from datetime import UTC, datetime

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.sql import DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE


class TestPreaggregationModel(ClickhouseTestMixin, BaseTest):
    def _insert_preaggregation_result(self, team_id, job_id, time_window_start, breakdown_value, test_uuid):
        """Helper to insert a preaggregation result using INSERT ... SELECT pattern."""
        # Build the breakdown array literal
        breakdown_literal = "[" + ", ".join(f"'{v}'" for v in breakdown_value) + "]"

        sync_execute(
            f"""
            INSERT INTO {DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE()} (
                team_id,
                job_id,
                time_window_start,
                breakdown_value,
                uniq_exact_state
            )
            SELECT
                %(team_id)s as team_id,
                toUUID(%(job_id)s) as job_id,
                toDateTime64(%(time_window_start)s, 6, 'UTC') as time_window_start,
                {breakdown_literal} as breakdown_value,
                initializeAggregation('uniqExactState', toUUID(%(test_uuid)s)) as uniq_exact_state
            """,
            {
                "team_id": team_id,
                "job_id": str(job_id),
                "time_window_start": time_window_start.strftime("%Y-%m-%d %H:%M:%S"),
                "test_uuid": str(test_uuid),
            },
        )

    def test_insert_and_read_preaggregation_results(self):
        job_id = uuid.uuid4()
        time_window_start = datetime(2024, 3, 8, 0, 0, 0, tzinfo=UTC)
        breakdown_value = ["safari", "mac"]
        test_uuid = uuid.uuid4()

        self._insert_preaggregation_result(self.team.id, job_id, time_window_start, breakdown_value, test_uuid)

        result = sync_execute(
            f"""
            SELECT
                team_id,
                job_id,
                time_window_start,
                breakdown_value,
                uniqExactMerge(uniq_exact_state) as uniq_count
            FROM {DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE()}
            WHERE
                team_id = %(team_id)s AND
                job_id = toUUID(%(job_id)s)
            GROUP BY team_id, job_id, time_window_start, breakdown_value
            """,
            {
                "team_id": self.team.id,
                "job_id": str(job_id),
            },
        )

        assert len(result) == 1
        row = result[0]
        assert row[0] == self.team.id
        assert row[1] == job_id
        assert row[2] == time_window_start
        assert row[3] == breakdown_value
        assert row[4] == 1

    def test_insert_multiple_rows_same_job(self):
        job_id = uuid.uuid4()
        time_window_start = datetime(2024, 3, 8, 0, 0, 0, tzinfo=UTC)

        for breakdown in [["chrome"], ["safari"], ["firefox"]]:
            test_uuid = uuid.uuid4()
            self._insert_preaggregation_result(self.team.id, job_id, time_window_start, breakdown, test_uuid)

        result = sync_execute(
            f"""
            SELECT
                breakdown_value,
                uniqExactMerge(uniq_exact_state) as uniq_count
            FROM {DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE()}
            WHERE
                team_id = %(team_id)s AND
                job_id = toUUID(%(job_id)s)
            GROUP BY team_id, job_id, time_window_start, breakdown_value
            ORDER BY breakdown_value
            """,
            {
                "team_id": self.team.id,
                "job_id": str(job_id),
            },
        )

        assert len(result) == 3
        breakdown_values = [row[0] for row in result]
        assert ["chrome"] in breakdown_values
        assert ["firefox"] in breakdown_values
        assert ["safari"] in breakdown_values

    def test_empty_breakdown_value(self):
        job_id = uuid.uuid4()
        time_window_start = datetime(2024, 3, 8, 0, 0, 0, tzinfo=UTC)
        test_uuid = uuid.uuid4()

        self._insert_preaggregation_result(self.team.id, job_id, time_window_start, [], test_uuid)

        result = sync_execute(
            f"""
            SELECT
                breakdown_value,
                uniqExactMerge(uniq_exact_state) as uniq_count
            FROM {DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE()}
            WHERE
                team_id = %(team_id)s AND
                job_id = toUUID(%(job_id)s)
            GROUP BY team_id, job_id, time_window_start, breakdown_value
            """,
            {
                "team_id": self.team.id,
                "job_id": str(job_id),
            },
        )

        assert len(result) == 1
        assert result[0][0] == []
        assert result[0][1] == 1
