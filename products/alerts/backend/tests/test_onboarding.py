from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import MagicMock, patch

import numpy as np
from parameterized import parameterized

from posthog.schema import HogQLQuery

from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.models.team import Team
from posthog.tasks.alerts.detectors import get_detector

from products.alerts.backend.evaluation.validation import validate_alert_config
from products.alerts.backend.facade.onboarding import create_default_ingestion_alert
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts_platform.backend.facade.scheduling import CalendarInterval, alert_check_offset
from products.product_analytics.backend.facade.models import Insight


class TestDefaultIngestionAlert(BaseTest):
    @parameterized.expand(
        [
            ("enabled", True, True, False, True, True),
            ("flag_off", False, True, False, True, False),
            ("no_creator", True, False, False, True, False),
            ("demo", True, True, True, True, False),
            ("email_unavailable", True, True, False, False, True),
        ]
    )
    @time_machine.travel("2026-10-01T11:30:00Z", tick=False)
    @patch("products.alerts.backend.facade.onboarding.is_email_available")
    @patch("products.alerts.backend.facade.onboarding.feature_enabled_or_false")
    @patch("posthog.models.team.team.Team.kick_off_demo_data_generation")
    def test_project_creation(
        self,
        _name: str,
        flag_enabled: bool,
        has_creator: bool,
        is_demo: bool,
        email_available: bool,
        expect_alert: bool,
        _mock_demo: MagicMock,
        mock_flag: MagicMock,
        mock_email: MagicMock,
    ) -> None:
        mock_flag.return_value = flag_enabled
        mock_email.return_value = email_available
        team = Team.objects.create_with_data(
            organization=self.organization,
            initiating_user=self.user if has_creator else None,
            timezone="Pacific/Auckland",
            is_demo=is_demo,
        )

        alerts = AlertConfiguration.objects.filter(team_id=team.id)
        assert alerts.count() == int(expect_alert)
        if not expect_alert:
            assert not Insight.objects.filter(team_id=team.id, filters__default_ingestion_alert=True).exists()
            return

        alert = alerts.get()
        assert alert.get_subscribed_users_emails() == [self.user.email]
        assert alert.enabled == email_available
        assert alert.skip_weekend
        assert alert.calculation_interval == "daily"
        assert alert.next_check_at == datetime(2026, 10, 18, 12, tzinfo=UTC) + alert_check_offset(
            CalendarInterval.DAILY, alert.id
        )
        validate_alert_config(
            alert.insight.query,
            alert.condition,
            alert.config,
            calculation_interval=alert.calculation_interval,
            detector_config=alert.detector_config,
        )

        assert create_default_ingestion_alert(team, self.user) is None
        alert.delete()
        assert create_default_ingestion_alert(team, self.user) is None
        assert not alerts.exists()

    @patch("products.alerts.backend.facade.onboarding.capture_exception")
    @patch("products.alerts.backend.facade.onboarding.feature_enabled_or_false", return_value=True)
    @patch("products.alerts.backend.facade.onboarding.is_email_available", return_value=True)
    @patch("products.alerts.backend.facade.onboarding.AlertSubscription.objects.create", side_effect=RuntimeError)
    def test_alert_failure_does_not_block_project_creation(
        self, _mock_subscription: MagicMock, _mock_email: MagicMock, _mock_flag: MagicMock, _mock_capture: MagicMock
    ) -> None:
        team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)

        assert Team.objects.filter(id=team.id).exists()
        assert not AlertConfiguration.objects.filter(team_id=team.id).exists()
        assert not Insight.objects.filter(team_id=team.id, filters__default_ingestion_alert=True).exists()


class TestIngestionComparison(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            ("increase", "UTC", 200, 400, 100.0, True),
            ("stop", "UTC", 200, 0, -100.0, True),
            ("small_counts", "UTC", 1, 3, 0.0, False),
            ("small_percentage", "UTC", 1000, 1100, 10.0, False),
            ("no_baseline", "UTC", 0, 200, 0.0, False),
            ("timezone", "America/New_York", 200, 0, -100.0, True),
        ]
    )
    @time_machine.travel("2026-10-19T12:00:00Z", tick=False)
    @patch("products.alerts.backend.facade.onboarding.feature_enabled_or_false", return_value=True)
    @patch("products.alerts.backend.facade.onboarding.is_email_available", return_value=True)
    def test_daily_ingestion_comparison(
        self,
        _name: str,
        timezone: str,
        previous_count: int,
        current_count: int,
        expected_change: float,
        expected_anomaly: bool,
        _mock_email: MagicMock,
        _mock_flag: MagicMock,
    ) -> None:
        self.team.timezone = timezone
        self.team.save()
        alert_id = create_default_ingestion_alert(self.team, self.user)
        assert alert_id is not None
        alert = AlertConfiguration.objects.get(team_id=self.team.id, id=alert_id)
        today = datetime.now(ZoneInfo(timezone)).date()
        for days_ago, count in [(2, previous_count), (1, current_count), (0, 1)]:
            ingested_at = datetime.combine(today - timedelta(days=days_ago), time(23), tzinfo=ZoneInfo(timezone))
            for _ in range(count):
                _create_event(
                    team=self.team,
                    event="example_event",
                    distinct_id="example-user",
                    timestamp=(ingested_at - timedelta(days=5)).isoformat(),
                    created_at=ingested_at,
                )

        query = HogQLQuery.model_validate(alert.insight.query["source"])
        query.query = query.query.replace("now()", "toDateTime({evaluation_time})")
        query.values = {"evaluation_time": datetime.now(UTC).isoformat()}
        result = HogQLQueryRunner(query=query, team=self.team).calculate()
        assert result.results is not None
        latest = result.results[-1]
        assert latest[0].date().isoformat() == (today - timedelta(days=1)).isoformat()
        assert tuple(latest[1:3]) == (current_count, previous_count)
        assert latest[5] == expected_change

        detector = get_detector(alert.detector_config)
        values = np.array([row[5] for row in result.results])
        assert detector.detect(values).is_anomaly == expected_anomaly
