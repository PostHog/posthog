from freezegun.api import freeze_time

from posthog.models.activity_logging.activity_log import Detail, Trigger, log_activity
from posthog.models.team.team import Team
from posthog.queries.app_metrics.historical_exports import historical_export_metrics, historical_exports_activity
from posthog.queries.app_metrics.test.test_app_metrics import create_app_metric
from posthog.test.base import BaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries, snapshot_postgres_queries

SAMPLE_PAYLOAD = {"dateRange": ["2021-06-10", "2022-06-12"], "parallelism": 1}


@freeze_time("2021-08-25T13:00:00Z")
class TestHistoricalExports(ClickhouseTestMixin, BaseTest):
    @snapshot_postgres_queries
    def test_historical_exports_activity_for_not_finished_export(self):
        self._create_activity_log(
            activity="job_triggered",
            detail=Detail(
                name="Some export plugin",
                trigger=Trigger(job_type="Export historical events V2", job_id="1234", payload=SAMPLE_PAYLOAD),
            ),
        )

        activities = historical_exports_activity(self.team.pk, 3)
        self.assertEqual(len(activities), 1)
        self.assertEqual(
            activities[0],
            {
                "job_id": "1234",
                "started_at": "2021-08-25T13:00:00+00:00",
                "status": "not_finished",
                "payload": SAMPLE_PAYLOAD,
            },
        )

    @snapshot_postgres_queries
    def test_historical_exports_activity_for_finished_export(self):
        with freeze_time("2021-08-25T11:00:00Z"):
            self._create_activity_log(
                activity="job_triggered",
                detail=Detail(
                    name="Some export plugin",
                    trigger=Trigger(job_type="Export historical events V2", job_id="1234", payload=SAMPLE_PAYLOAD),
                ),
            )
        with freeze_time("2021-08-25T13:00:00Z"):
            self._create_activity_log(
                activity="export_success",
                detail=Detail(
                    name="Some export plugin",
                    trigger=Trigger(job_type="Export historical events V2", job_id="1234", payload={}),
                ),
            )

        activities = historical_exports_activity(self.team.pk, 3)
        self.assertEqual(len(activities), 1)
        self.assertEqual(
            activities[0],
            {
                "job_id": "1234",
                "started_at": "2021-08-25T11:00:00+00:00",
                "finished_at": "2021-08-25T13:00:00+00:00",
                "status": "success",
                "payload": SAMPLE_PAYLOAD,
                "duration": 2 * 60 * 60,
            },
        )

    @snapshot_postgres_queries
    def test_historical_exports_activity_for_failed_export(self):
        with freeze_time("2021-08-25T11:00:00Z"):
            self._create_activity_log(
                activity="job_triggered",
                detail=Detail(
                    name="Some export plugin",
                    trigger=Trigger(job_type="Export historical events V2", job_id="1234", payload=SAMPLE_PAYLOAD),
                ),
            )
        with freeze_time("2021-08-25T13:00:00Z"):
            self._create_activity_log(
                activity="export_fail",
                detail=Detail(
                    name="Some export plugin",
                    trigger=Trigger(job_type="Export historical events V2", job_id="1234", payload={}),
                ),
            )

        activities = historical_exports_activity(self.team.pk, 3)
        self.assertEqual(len(activities), 1)
        self.assertEqual(
            activities[0],
            {
                "job_id": "1234",
                "started_at": "2021-08-25T11:00:00+00:00",
                "finished_at": "2021-08-25T13:00:00+00:00",
                "status": "fail",
                "payload": SAMPLE_PAYLOAD,
                "duration": 2 * 60 * 60,
            },
        )

    def test_historical_exports_activity_ignores_unrelated_entries(self):
        self._create_activity_log(
            activity="job_triggered",
            detail=Detail(
                name="Some export plugin",
                trigger=Trigger(job_type="Export historical events V2", job_id="1234", payload=SAMPLE_PAYLOAD),
            ),
        )

        # Different job finishing
        self._create_activity_log(
            activity="export_success",
            detail=Detail(
                name="Some export plugin",
                trigger=Trigger(job_type="Export historical events V2", job_id="another", payload={}),
            ),
        )
        # Different plugin
        self._create_activity_log(
            item_id=2,
            activity="export_success",
            detail=Detail(
                name="Some export plugin",
                trigger=Trigger(job_type="Export historical events V2", job_id="1234", payload={}),
            ),
        )
        # Different plugin
        another_team = Team.objects.create(organization=self.organization)
        self._create_activity_log(
            team_id=another_team.pk,
            activity="export_success",
            detail=Detail(
                name="Some export plugin",
                trigger=Trigger(job_type="Export historical events V2", job_id="1234", payload={}),
            ),
        )
        # Non-export job
        self._create_activity_log(
            team_id=self.team.pk,
            activity="job_triggered",
            detail=Detail(
                name="Some export plugin",
                trigger=Trigger(job_type="Another job", job_id="1234", payload={}),
            ),
        )

        activities = historical_exports_activity(self.team.pk, 3)
        self.assertEqual(len(activities), 1)
        self.assertEqual(
            activities[0],
            {
                "job_id": "1234",
                "started_at": "2021-08-25T13:00:00+00:00",
                "status": "not_finished",
                "payload": SAMPLE_PAYLOAD,
            },
        )

    def test_historical_exports_orders_activity_by_started_at(self):
        for hour in range(10, 15):
            with freeze_time(f"2021-08-25T{hour}:00:00Z"):
                self._create_activity_log(
                    activity="job_triggered",
                    detail=Detail(
                        name="Some export plugin",
                        trigger=Trigger(
                            job_type="Export historical events V2", job_id=str(hour), payload=SAMPLE_PAYLOAD
                        ),
                    ),
                )

        activities = historical_exports_activity(self.team.pk, 3)
        start_times = [activity["started_at"] for activity in activities]
        self.assertEqual(
            start_times,
            [
                "2021-08-25T14:00:00+00:00",
                "2021-08-25T13:00:00+00:00",
                "2021-08-25T12:00:00+00:00",
                "2021-08-25T11:00:00+00:00",
                "2021-08-25T10:00:00+00:00",
            ],
        )

    @snapshot_postgres_queries
    @snapshot_clickhouse_queries
    def test_historical_export_metrics(self):
        with freeze_time("2021-08-25T00:00:00Z"):
            self._create_activity_log(
                activity="job_triggered",
                detail=Detail(
                    name="Some export plugin",
                    trigger=Trigger(job_type="Export historical events V2", job_id="1234", payload=SAMPLE_PAYLOAD),
                ),
            )
        with freeze_time("2021-08-25T05:00:00Z"):
            self._create_activity_log(
                activity="export_success",
                detail=Detail(
                    name="Some export plugin",
                    trigger=Trigger(job_type="Export historical events V2", job_id="1234", payload={}),
                ),
            )

        create_app_metric(
            team_id=self.team.pk,
            category="exportEvents",
            plugin_config_id=3,
            job_id="1234",
            timestamp="2021-08-25T00:10:00Z",
            successes=102,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="exportEvents",
            plugin_config_id=3,
            job_id="1234",
            timestamp="2021-08-25T02:55:00Z",
            failures=2,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="exportEvents",
            plugin_config_id=3,
            job_id="1234",
            timestamp="2021-08-25T03:10:00Z",
            successes=10,
        )

        results = historical_export_metrics(self.team, 3, "1234")

        self.assertEqual(
            results,
            {
                "metrics": {
                    "dates": [
                        "2021-08-25 00:00:00",
                        "2021-08-25 01:00:00",
                        "2021-08-25 02:00:00",
                        "2021-08-25 03:00:00",
                        "2021-08-25 04:00:00",
                        "2021-08-25 05:00:00",
                    ],
                    "successes": [102, 0, 0, 10, 0, 0],
                    "successes_on_retry": [0, 0, 0, 0, 0, 0],
                    "failures": [0, 0, 2, 0, 0, 0],
                    "totals": {"successes": 112, "successes_on_retry": 0, "failures": 2},
                },
                "summary": {
                    "duration": 5 * 60 * 60,
                    "finished_at": "2021-08-25T05:00:00+00:00",
                    "job_id": "1234",
                    "payload": SAMPLE_PAYLOAD,
                    "started_at": "2021-08-25T00:00:00+00:00",
                    "status": "success",
                },
            },
        )

    def _create_activity_log(self, **kwargs):
        log_activity(
            **{
                "organization_id": self.team.organization.id,
                "team_id": self.team.pk,
                "user": self.user,
                "item_id": 3,
                "scope": "PluginConfig",
                **kwargs,
            }
        )
