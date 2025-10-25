import json
import datetime as dt

from freezegun.api import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest import mock

from rest_framework import status

from posthog.api.test.batch_exports.conftest import start_test_worker
from posthog.api.test.batch_exports.operations import create_batch_export_ok
from posthog.batch_exports.models import BatchExportRun
from posthog.models.activity_logging.activity_log import Detail, Trigger, log_activity
from posthog.models.plugin import Plugin, PluginConfig
from posthog.models.utils import UUIDT
from posthog.queries.app_metrics.test.test_app_metrics import create_app_metric
from posthog.temporal.common.client import sync_connect

SAMPLE_PAYLOAD = {"dateRange": ["2021-06-10", "2022-06-12"], "parallelism": 1}


@freeze_time("2021-12-05T13:23:00Z")
class TestAppMetricsAPI(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def setUp(self):
        super().setUp()
        self.plugin = Plugin.objects.create(organization=self.organization)
        self.plugin_config = PluginConfig.objects.create(plugin=self.plugin, team=self.team, enabled=True, order=1)

        self.organization.save()

    def test_retrieve(self):
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=self.plugin_config.id,
            timestamp="2021-12-03T00:00:00Z",
            successes=3,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=self.plugin_config.id,
            timestamp="2021-12-04T00:00:00Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="SomeError",
        )

        response = self.client.get(
            f"/api/projects/@current/app_metrics/{self.plugin_config.id}?category=processEvent&date_from=-7d"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "metrics": {
                    "dates": [
                        "2021-11-28",
                        "2021-11-29",
                        "2021-11-30",
                        "2021-12-01",
                        "2021-12-02",
                        "2021-12-03",
                        "2021-12-04",
                        "2021-12-05",
                    ],
                    "successes": [0, 0, 0, 0, 0, 3, 0, 0],
                    "successes_on_retry": [0, 0, 0, 0, 0, 0, 0, 0],
                    "failures": [0, 0, 0, 0, 0, 0, 1, 0],
                    "totals": {"successes": 3, "successes_on_retry": 0, "failures": 1},
                },
                "errors": [
                    {
                        "error_type": "SomeError",
                        "count": 1,
                        "last_seen": "2021-12-04T00:00:00Z",
                    }
                ],
            },
        )

    def test_retrieve_batch_export_runs_app_metrics(self):
        """Test batch export metrics returned by app metrics endpoint."""
        destination_data = {
            "type": "S3",
            "config": {
                "bucket_name": "my-production-s3-bucket",
                "region": "us-east-1",
                "prefix": "posthog-events/",
                "aws_access_key_id": "abc123",
                "aws_secret_access_key": "secret",
                "include_events": ["test-event"],
            },
        }

        batch_export_data = {
            "name": "my-production-s3-bucket-destination",
            "destination": destination_data,
            "interval": "hour",
        }

        temporal = sync_connect()

        now = dt.datetime(2021, 12, 5, 13, 23, 0, tzinfo=dt.UTC)
        with start_test_worker(temporal):
            response = create_batch_export_ok(
                self.client,
                self.team.pk,
                json.dumps(batch_export_data),
            )

            batch_export_id = response["id"]
            for days_ago in range(0, 7):
                last_updated_at = now - dt.timedelta(days=days_ago)

                with freeze_time(last_updated_at):
                    # Since 'last_updated_at' uses 'auto_now', passing the argument is ignored.
                    # We have to re-freeze time to get each run created on a single date.
                    BatchExportRun.objects.create(
                        batch_export_id=batch_export_id,
                        data_interval_end=last_updated_at,
                        data_interval_start=last_updated_at - dt.timedelta(hours=1),
                        status=BatchExportRun.Status.COMPLETED,
                    )
                    BatchExportRun.objects.create(
                        batch_export_id=batch_export_id,
                        data_interval_end=last_updated_at,
                        data_interval_start=last_updated_at - dt.timedelta(hours=1),
                        status=BatchExportRun.Status.COMPLETED,
                    )
                    BatchExportRun.objects.create(
                        batch_export_id=batch_export_id,
                        data_interval_end=last_updated_at,
                        data_interval_start=last_updated_at - dt.timedelta(hours=1),
                        status=BatchExportRun.Status.COMPLETED,
                    )
                    BatchExportRun.objects.create(
                        batch_export_id=batch_export_id,
                        data_interval_end=last_updated_at - dt.timedelta(hours=2),
                        data_interval_start=last_updated_at - dt.timedelta(hours=3),
                        status=BatchExportRun.Status.FAILED,
                    )
                    BatchExportRun.objects.create(
                        batch_export_id=batch_export_id,
                        data_interval_end=last_updated_at - dt.timedelta(hours=2),
                        data_interval_start=last_updated_at - dt.timedelta(hours=3),
                        status=BatchExportRun.Status.FAILED_RETRYABLE,
                    )

            response = self.client.get(f"/api/projects/@current/app_metrics/{batch_export_id}?date_from=-7d")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                response.json(),
                {
                    "metrics": {
                        "dates": [
                            "2021-11-29",
                            "2021-11-30",
                            "2021-12-01",
                            "2021-12-02",
                            "2021-12-03",
                            "2021-12-04",
                            "2021-12-05",
                        ],
                        "successes": [3, 3, 3, 3, 3, 3, 3],
                        "successes_on_retry": [0, 0, 0, 0, 0, 0, 0],
                        "failures": [2, 2, 2, 2, 2, 2, 2],
                        "totals": {"successes": 21, "successes_on_retry": 0, "failures": 14},
                    },
                    "errors": None,
                },
            )

    def test_retrieve_batch_export_runs_app_metrics_defaults_to_zero(self):
        """Test batch export metrics returned by app metrics endpoint."""
        destination_data = {
            "type": "S3",
            "config": {
                "bucket_name": "my-production-s3-bucket",
                "region": "us-east-1",
                "prefix": "posthog-events/",
                "aws_access_key_id": "abc123",
                "aws_secret_access_key": "secret",
                "exclude_events": ["exclude-me"],
            },
        }

        batch_export_data = {
            "name": "my-production-s3-bucket-destination",
            "destination": destination_data,
            "interval": "hour",
        }

        temporal = sync_connect()
        now = dt.datetime(2021, 12, 5, 13, 23, 0, tzinfo=dt.UTC)

        with start_test_worker(temporal):
            response = create_batch_export_ok(
                self.client,
                self.team.pk,
                json.dumps(batch_export_data),
            )
            batch_export_id = response["id"]

            for days_ago in range(0, 7):
                last_updated_at = now - dt.timedelta(days=days_ago)

                with freeze_time(last_updated_at):
                    # Since 'last_updated_at' uses 'auto_now', passing the argument is ignored.
                    # We have to re-freeze time to get each run created on a single date.
                    BatchExportRun.objects.create(
                        batch_export_id=batch_export_id,
                        data_interval_end=last_updated_at,
                        data_interval_start=last_updated_at - dt.timedelta(hours=1),
                        status=BatchExportRun.Status.COMPLETED,
                    )

            response = self.client.get(f"/api/projects/@current/app_metrics/{batch_export_id}?date_from=-7d")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                response.json(),
                {
                    "metrics": {
                        "dates": [
                            "2021-11-29",
                            "2021-11-30",
                            "2021-12-01",
                            "2021-12-02",
                            "2021-12-03",
                            "2021-12-04",
                            "2021-12-05",
                        ],
                        "successes": [1, 1, 1, 1, 1, 1, 1],
                        "successes_on_retry": [0, 0, 0, 0, 0, 0, 0],
                        "failures": [0, 0, 0, 0, 0, 0, 0],
                        "totals": {"successes": 7, "successes_on_retry": 0, "failures": 0},
                    },
                    "errors": None,
                },
            )

    def test_list_historical_exports(self):
        self._create_activity_log(
            activity="job_triggered",
            detail=Detail(
                name="Some export plugin",
                trigger=Trigger(job_type="Export historical events V2", job_id="1234", payload={}),
            ),
        )

        response = self.client.get(f"/api/projects/@current/app_metrics/{self.plugin_config.id}/historical_exports")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "results": [
                    {
                        "job_id": "1234",
                        "created_at": "2021-12-05T13:23:00Z",
                        "status": "not_finished",
                        "payload": {},
                        "created_by": mock.ANY,
                    }
                ]
            },
        )

    def test_retrieve_historical_export(self):
        with freeze_time("2021-08-25T01:00:00Z"):
            self._create_activity_log(
                activity="job_triggered",
                detail=Detail(
                    name="Some export plugin",
                    trigger=Trigger(
                        job_type="Export historical events V2",
                        job_id="1234",
                        payload=SAMPLE_PAYLOAD,
                    ),
                ),
            )
        with freeze_time("2021-08-25T05:00:00Z"):
            self._create_activity_log(
                activity="export_success",
                detail=Detail(
                    name="Some export plugin",
                    trigger=Trigger(
                        job_type="Export historical events V2",
                        job_id="1234",
                        payload={},
                    ),
                ),
            )

        create_app_metric(
            team_id=self.team.pk,
            category="exportEvents",
            plugin_config_id=self.plugin_config.id,
            job_id="1234",
            timestamp="2021-08-25T01:10:00Z",
            successes=102,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="exportEvents",
            plugin_config_id=self.plugin_config.id,
            job_id="1234",
            timestamp="2021-08-25T02:55:00Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="SomeError",
        )
        create_app_metric(
            team_id=self.team.pk,
            category="exportEvents",
            plugin_config_id=self.plugin_config.id,
            job_id="1234",
            timestamp="2021-08-25T03:10:00Z",
            successes=10,
        )

        response = self.client.get(
            f"/api/projects/@current/app_metrics/{self.plugin_config.id}/historical_exports/1234"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "metrics": {
                    "dates": [
                        "2021-08-25 00:00:00",
                        "2021-08-25 01:00:00",
                        "2021-08-25 02:00:00",
                        "2021-08-25 03:00:00",
                        "2021-08-25 04:00:00",
                        "2021-08-25 05:00:00",
                        "2021-08-25 06:00:00",
                    ],
                    "successes": [0, 102, 0, 10, 0, 0, 0],
                    "successes_on_retry": [0, 0, 0, 0, 0, 0, 0],
                    "failures": [0, 0, 1, 0, 0, 0, 0],
                    "totals": {
                        "successes": 112,
                        "successes_on_retry": 0,
                        "failures": 1,
                    },
                },
                "summary": {
                    "duration": 4 * 60 * 60,
                    "finished_at": "2021-08-25T05:00:00Z",
                    "job_id": "1234",
                    "payload": SAMPLE_PAYLOAD,
                    "status": "success",
                    "created_at": "2021-08-25T01:00:00Z",
                    "created_by": mock.ANY,
                },
                "errors": [
                    {
                        "error_type": "SomeError",
                        "count": 1,
                        "last_seen": "2021-08-25T02:55:00Z",
                    }
                ],
            },
        )

    def test_error_details(self):
        error_uuid = str(UUIDT())
        create_app_metric(
            team_id=self.team.pk,
            category="exportEvents",
            plugin_config_id=self.plugin_config.id,
            job_id="1234",
            timestamp="2021-08-25T02:55:00Z",
            failures=1,
            error_uuid=error_uuid,
            error_type="SomeError",
            error_details={"event": {}},
        )

        response = self.client.get(
            f"/api/projects/@current/app_metrics/{self.plugin_config.id}/error_details?category=exportEvents&error_type=SomeError"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "result": [
                    {
                        "error_uuid": error_uuid,
                        "error_type": "SomeError",
                        "error_details": {"event": {}},
                        "timestamp": "2021-08-25T02:55:00Z",
                    }
                ]
            },
        )

    def _create_activity_log(self, **kwargs):
        log_activity(
            **{  # Using dict form so that kwargs can override these defaults
                "organization_id": self.team.organization.id,
                "team_id": self.team.pk,
                "user": self.user,
                "item_id": self.plugin_config.id,
                "was_impersonated": False,
                "scope": "PluginConfig",
                **kwargs,
            }
        )
