import uuid
from datetime import UTC, datetime

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.sql import (
    DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE,
    WRITABLE_PREAGGREGATION_RESULTS_TABLE,
)


class TestPreaggregationModel(ClickhouseTestMixin, BaseTest):
    def test_insert_and_read_preaggregation_results(self):
        job_id = uuid.uuid4()
        time_window_start = datetime(2024, 3, 8, 0, 0, 0, tzinfo=UTC)
        breakdown_value = ["safari", "mac"]
        test_uuid = uuid.uuid4()

        # Insert a row using the writable distributed table
        sync_execute(
            f"""
            INSERT INTO {WRITABLE_PREAGGREGATION_RESULTS_TABLE()} (
                team_id,
                job_id,
                time_window_start,
                breakdown_value,
                uniq_exact_state
            ) VALUES (
                %(team_id)s,
                %(job_id)s,
                %(time_window_start)s,
                %(breakdown_value)s,
                uniqExactState(%(test_uuid)s)
            )
            """,
            {
                "team_id": self.team.id,
                "job_id": job_id,
                "time_window_start": time_window_start,
                "breakdown_value": breakdown_value,
                "test_uuid": test_uuid,
            },
        )

        # Read it back from the distributed table
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
                job_id = %(job_id)s
            GROUP BY team_id, job_id, time_window_start, breakdown_value
            """,
            {
                "team_id": self.team.id,
                "job_id": job_id,
            },
        )

        assert len(result) == 1
        row = result[0]
        assert row[0] == self.team.id  # team_id
        assert row[1] == job_id  # job_id
        assert row[2] == time_window_start  # time_window_start
        assert row[3] == breakdown_value  # breakdown_value
        assert row[4] == 1  # uniq_count (one unique UUID)

    def test_insert_multiple_rows_same_job(self):
        job_id = uuid.uuid4()
        time_window_start = datetime(2024, 3, 8, 0, 0, 0, tzinfo=UTC)

        # Insert multiple rows with different breakdown values
        for breakdown in [["chrome"], ["safari"], ["firefox"]]:
            test_uuid = uuid.uuid4()
            sync_execute(
                f"""
                INSERT INTO {WRITABLE_PREAGGREGATION_RESULTS_TABLE()} (
                    team_id,
                    job_id,
                    time_window_start,
                    breakdown_value,
                    uniq_exact_state
                ) VALUES (
                    %(team_id)s,
                    %(job_id)s,
                    %(time_window_start)s,
                    %(breakdown_value)s,
                    uniqExactState(%(test_uuid)s)
                )
                """,
                {
                    "team_id": self.team.id,
                    "job_id": job_id,
                    "time_window_start": time_window_start,
                    "breakdown_value": breakdown,
                    "test_uuid": test_uuid,
                },
            )

        # Read all rows for this job
        result = sync_execute(
            f"""
            SELECT
                breakdown_value,
                uniqExactMerge(uniq_exact_state) as uniq_count
            FROM {DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE()}
            WHERE
                team_id = %(team_id)s AND
                job_id = %(job_id)s
            GROUP BY team_id, job_id, time_window_start, breakdown_value
            ORDER BY breakdown_value
            """,
            {
                "team_id": self.team.id,
                "job_id": job_id,
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

        # Insert with empty breakdown (no GROUP BY case)
        sync_execute(
            f"""
            INSERT INTO {WRITABLE_PREAGGREGATION_RESULTS_TABLE()} (
                team_id,
                job_id,
                time_window_start,
                breakdown_value,
                uniq_exact_state
            ) VALUES (
                %(team_id)s,
                %(job_id)s,
                %(time_window_start)s,
                %(breakdown_value)s,
                uniqExactState(%(test_uuid)s)
            )
            """,
            {
                "team_id": self.team.id,
                "job_id": job_id,
                "time_window_start": time_window_start,
                "breakdown_value": [],
                "test_uuid": test_uuid,
            },
        )

        result = sync_execute(
            f"""
            SELECT
                breakdown_value,
                uniqExactMerge(uniq_exact_state) as uniq_count
            FROM {DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE()}
            WHERE
                team_id = %(team_id)s AND
                job_id = %(job_id)s
            GROUP BY team_id, job_id, time_window_start, breakdown_value
            """,
            {
                "team_id": self.team.id,
                "job_id": job_id,
            },
        )

        assert len(result) == 1
        assert result[0][0] == []  # empty breakdown
        assert result[0][1] == 1  # one unique UUID
