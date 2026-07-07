from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from products.data_modeling.backend.logic.saved_query_freshness import saved_query_materialized_at
from products.data_modeling.backend.models import DataModelingJob
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery


class TestSavedQueryMaterializedAt(BaseTest):
    @parameterized.expand(
        [
            # (name, saved_query_last_run_minutes_ago, jobs as (status, engine, minutes_ago), expected_minutes_ago)
            # v2 DAG runs write DataModelingJob but never saved_query.last_run_at
            ("completed_job_beats_frozen_saved_query", 3 * 24 * 60, [("Completed", "clickhouse", 5)], 5),
            (
                "newest_failed_job_ignored",
                3 * 24 * 60,
                [("Completed", "clickhouse", 120), ("Failed", "clickhouse", 5)],
                120,
            ),
            (
                "duckgres_shadow_job_ignored",
                3 * 24 * 60,
                [("Completed", "clickhouse", 120), ("Completed", "duckgres", 5)],
                120,
            ),
            ("running_job_ignored", 30, [("Running", "clickhouse", 1)], 30),
            ("no_jobs_falls_back_to_saved_query", 30, [], 30),
            ("saved_query_newer_than_jobs_wins", 5, [("Completed", "clickhouse", 120)], 5),
            ("never_materialized_returns_none", None, [], None),
        ]
    )
    def test_returns_latest_successful_clickhouse_materialization(
        self, _name, saved_query_minutes_ago, jobs, expected_minutes_ago
    ):
        now = timezone.now()
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="view",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            last_run_at=now - timedelta(minutes=saved_query_minutes_ago) if saved_query_minutes_ago else None,
        )
        for job_status, engine, minutes_ago in jobs:
            job = DataModelingJob.objects.create(
                team=self.team,
                saved_query=saved_query,
                status=job_status,
                engine=engine,
                last_run_at=now - timedelta(minutes=minutes_ago),
            )
            DataModelingJob.objects.filter(id=job.id).update(created_at=now - timedelta(minutes=minutes_ago))

        expected = now - timedelta(minutes=expected_minutes_ago) if expected_minutes_ago else None
        self.assertEqual(saved_query_materialized_at(saved_query), expected)
