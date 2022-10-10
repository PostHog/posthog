from freezegun.api import freeze_time

from posthog.models.activity_logging.activity_log import Detail, Trigger, log_activity
from posthog.models.team.team import Team
from posthog.queries.app_metrics.historical_exports import historical_exports_activity
from posthog.test.base import BaseTest, QueryMatchingTest, snapshot_postgres_queries

SAMPLE_PAYLOAD = {"dateRange": ["2021-10-10", "2022-10-12"], "parallelism": 1}


@freeze_time("2021-08-25T13:00:00Z")
class TestHistoricalExports(BaseTest, QueryMatchingTest):
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
