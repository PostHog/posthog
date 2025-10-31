import uuid
import contextlib
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest import mock

from django.test import override_settings

from structlog.types import FilteringBoundLogger

from posthog.models import Team
from posthog.tasks.usage_report import ExternalDataJob
from posthog.temporal.data_imports.row_tracking import (
    finish_row_tracking,
    increment_rows,
    setup_row_tracking,
    will_hit_billing_limit,
)
from posthog.warehouse.models import ExternalDataSource


class TestRowTracking(BaseTest):
    def _logger(self) -> FilteringBoundLogger:
        return mock.MagicMock()

    @contextlib.contextmanager
    def _setup_limits(self, limit: int):
        from ee.api.test.test_billing import create_billing_customer

        with mock.patch("ee.api.billing.requests.get") as mock_billing_request:
            mock_res = create_billing_customer()
            usage_summary = mock_res.get("usage_summary") or {}
            mock_billing_request.return_value.status_code = 200
            mock_billing_request.return_value.json.return_value = {
                "license": {
                    "type": "scale",
                },
                "customer": {
                    **mock_res,
                    "usage_summary": {**usage_summary, "rows_synced": {"limit": limit, "usage": 0}},
                },
            }

            yield

    @contextlib.contextmanager
    def _setup_redis_rows(self, rows: int, team_id: Optional[int] = None):
        with override_settings(DATA_WAREHOUSE_REDIS_HOST="localhost", DATA_WAREHOUSE_REDIS_PORT="6379"):
            t_id = team_id or self.team.pk

            schema_id = str(uuid.uuid4())
            setup_row_tracking(t_id, schema_id)
            increment_rows(t_id, schema_id, rows)

            yield

            finish_row_tracking(t_id, schema_id)

    def _run(self, source: ExternalDataSource, limit: int) -> bool:
        from ee.models.license import License

        License.objects.create(
            key="12345::67890",
            plan="enterprise",
            valid_until=datetime(2038, 1, 19, 3, 14, 7, tzinfo=ZoneInfo("UTC")),
        )

        with (
            override_settings(DATA_WAREHOUSE_REDIS_HOST="localhost", DATA_WAREHOUSE_REDIS_PORT="6379"),
            self._setup_limits(limit),
            freeze_time("2024-01-01 12:00:00"),
        ):
            return will_hit_billing_limit(team_id=self.team.pk, source=source, logger=self._logger())

    def _create_source(self) -> ExternalDataSource:
        with freeze_time(datetime(2023, 12, 20)):
            return ExternalDataSource.objects.create(team=self.team)

    def test_row_tracking(self):
        source = self._create_source()
        assert self._run(source, 10) is False

    def test_row_tracking_with_previous_jobs(self):
        source = self._create_source()
        ExternalDataJob.objects.create(
            team=self.team,
            rows_synced=11,
            pipeline=source,
            finished_at=datetime.now(),
            billable=True,
            status=ExternalDataJob.Status.COMPLETED,
        )

        assert self._run(source, 10) is True

    def test_row_tracking_with_previous_incomplete_jobs(self):
        source = self._create_source()
        ExternalDataJob.objects.create(
            team=self.team,
            rows_synced=11,
            pipeline=source,
            finished_at=datetime.now(),
            billable=True,
            status=ExternalDataJob.Status.RUNNING,
        )

        assert self._run(source, 10) is False

    def test_row_tracking_with_previous_no_finished_at_jobs(self):
        source = self._create_source()
        ExternalDataJob.objects.create(
            team=self.team,
            rows_synced=11,
            pipeline=source,
            finished_at=None,
            billable=True,
            status=ExternalDataJob.Status.COMPLETED,
        )

        assert self._run(source, 10) is False

    def test_row_tracking_with_previous_unbillable_jobs(self):
        source = self._create_source()
        ExternalDataJob.objects.create(
            team=self.team,
            rows_synced=11,
            pipeline=source,
            finished_at=datetime.now(),
            billable=False,
            status=ExternalDataJob.Status.COMPLETED,
        )

        assert self._run(source, 10) is False

    def test_row_tracking_with_in_progress_rows(self):
        source = self._create_source()
        with self._setup_redis_rows(20):
            assert self._run(source, 10) is True

    def test_row_tracking_with_previous_rows_from_other_team_in_org(self):
        another_team = Team.objects.create(organization=self.organization)
        source = self._create_source()
        ExternalDataJob.objects.create(
            team=another_team,
            rows_synced=11,
            pipeline=source,
            finished_at=datetime.now(),
            billable=True,
            status=ExternalDataJob.Status.COMPLETED,
        )

        assert self._run(source, 10) is True

    def test_row_tracking_with_in_progress_rows_from_other_team_in_org(self):
        another_team = Team.objects.create(organization=self.organization)
        source = self._create_source()

        with self._setup_redis_rows(20, team_id=another_team.pk):
            assert self._run(source, 10) is True
