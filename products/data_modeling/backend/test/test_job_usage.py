from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster, ConnectionInfo
from posthog.clickhouse.workload import Workload

from products.data_modeling.backend.models.data_modeling_job import DataModelingJob, DataModelingJobEngine
from products.data_modeling.dags.job_usage import USAGE_SQL, JobUsageCollector


@time_machine.travel("2026-10-16T12:00:00Z", tick=False)
class TestJobUsageCollector(BaseTest):
    def test_archive_fragments_are_counted_once(self) -> None:
        started = datetime(2026, 10, 15, 20, tzinfo=UTC)
        sync_execute(
            """INSERT INTO sharded_query_log_archive_v3
            (initial_query_start_time, team_id, initial_query_id, is_initial_query, type,
             event_time_microseconds, read_bytes, read_rows, ProfileEvents_OSCPUVirtualTimeMicroseconds,
             lc_temporal__workflow_id, lc_temporal__workflow_run_id, lc_feature) VALUES""",
            [
                (
                    started,
                    self.team.id,
                    query_id,
                    1,
                    "QueryFinish",
                    started,
                    read_bytes,
                    2,
                    10,
                    "example-refresh",
                    "run-1",
                    feature,
                )
                for query_id, read_bytes, feature in [
                    ("probe", 100, "data_modeling"),
                    ("probe", 20, "data_modeling"),
                    ("materialize", 30, "data_modeling"),
                    ("unrelated", 1000, "other"),
                ]
            ],
            workload=Workload.OFFLINE,
        )
        rows = sync_execute(
            USAGE_SQL,
            {
                "start": started,
                "end": started + timedelta(hours=1),
            },
            workload=Workload.OFFLINE,
            external_tables=[
                {
                    "name": "model_usage_jobs",
                    "structure": [("team_id", "Int64"), ("workflow_id", "String"), ("workflow_run_id", "String")],
                    "data": [(self.team.id, "example-refresh", "run-1")],
                }
            ],
        )
        self.assertEqual(rows, [(self.team.id, "example-refresh", "run-1", 150, 6, 30, 2)])

    def test_replaces_totals_and_leaves_missing_and_ambiguous_runs_unknown(self) -> None:
        finished = datetime(2026, 10, 15, 20, tzinfo=UTC)
        base = {
            "team": self.team,
            "status": "Completed",
            "last_run_at": finished,
            "workflow_id": "example-refresh",
            "workflow_run_id": "run-1",
        }
        measured = DataModelingJob.objects.create(**base)
        missing = DataModelingJob.objects.create(**{**base, "workflow_run_id": "missing"})
        duplicate = DataModelingJob.objects.create(**{**base, "workflow_run_id": "duplicate"})
        DataModelingJob.objects.create(
            **{**base, "workflow_run_id": "duplicate", "last_run_at": finished - timedelta(days=1)}
        )
        # Managed warehouse runs record their own read_bytes, so the archive must not overwrite them.
        managed = DataModelingJob.objects.create(
            **{
                **base,
                "workflow_run_id": "managed",
                "engine": DataModelingJobEngine.MANAGED_WAREHOUSE,
                "read_bytes": 345,
            }
        )
        DataModelingJob.objects.filter(team=self.team).update(created_at=finished - timedelta(hours=1))
        bootstrap_client = MagicMock()
        bootstrap_client.execute.return_value = [("ops.example.com", 9000, 1, 1, "online", "ops")]
        cluster = ClickhouseCluster(bootstrap_client)
        client = MagicMock()
        client.execute.return_value = [(self.team.id, "example-refresh", "run-1", 4096, 800, 2000, 4)]
        with patch.object(ConnectionInfo, "make_pool") as make_pool:
            make_pool.return_value.get_client.return_value.__enter__.return_value = client
            JobUsageCollector.collect(cluster, finished.date(), {})
            JobUsageCollector.collect(cluster, finished.date(), {})
        sent = {key for call in client.execute.call_args_list for key in call.kwargs["external_tables"][0]["data"]}
        self.assertNotIn((self.team.id, "example-refresh", "managed"), sent)
        managed.refresh_from_db()
        self.assertEqual(managed.read_bytes, 345)
        measured.refresh_from_db()
        missing.refresh_from_db()
        duplicate.refresh_from_db()
        self.assertEqual(
            (measured.read_bytes, measured.read_rows, measured.cpu_microseconds, measured.query_count),
            (4096, 800, 2000, 4),
        )
        self.assertIsNotNone(measured.usage_updated_at)
        self.assertIsNone(missing.read_bytes)
        self.assertIsNone(duplicate.read_bytes)
        self.assertIsNone(duplicate.usage_updated_at)

    def test_reads_the_full_run_when_it_crosses_midnight(self) -> None:
        job = DataModelingJob.objects.create(
            team=self.team,
            status="Failed",
            workflow_id="cross-midnight",
            workflow_run_id="run-1",
            last_run_at=datetime(2026, 10, 15, 2, tzinfo=UTC),
        )
        created = datetime(2026, 10, 14, 23, tzinfo=UTC)
        DataModelingJob.objects.filter(id=job.id).update(created_at=created)
        cluster = MagicMock()
        cluster.any_host_by_role.return_value.result.return_value = [
            (self.team.id, "cross-midnight", "run-1", 10, 2, 0, 2)
        ]
        JobUsageCollector.collect(cluster, datetime(2026, 10, 15).date(), {})
        read = cluster.any_host_by_role.call_args.args[0]
        client = MagicMock()
        read(client)
        self.assertEqual(client.execute.call_args.args[1]["start"], created)
        self.assertEqual(
            client.execute.call_args.kwargs["external_tables"][0]["data"], [(self.team.id, "cross-midnight", "run-1")]
        )
        job.refresh_from_db()
        self.assertEqual(job.read_bytes, 10)
