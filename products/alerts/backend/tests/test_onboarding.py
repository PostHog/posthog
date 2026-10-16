from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import TrendsQuery

from posthog.api.services.query import ExecutionMode
from posthog.models import User
from posthog.models.team import Team

from products.alerts.backend.evaluation.detector import evaluate_with_detector, extract_detector_series
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
        with self.captureOnCommitCallbacks(execute=True):
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
        assert not alert.skip_weekend
        assert alert.calculation_interval == "daily"
        assert alert.detector_config is not None
        assert alert.detector_config["type"] == "knn"
        assert alert.detector_config["window"] == 14
        assert alert.detector_config["threshold"] == 0.99
        assert alert.detector_config["n_neighbors"] == 5
        assert alert.detector_config["method"] == "largest"
        assert alert.next_check_at == datetime(2026, 10, 18, 12, tzinfo=UTC) + alert_check_offset(
            CalendarInterval.DAILY, alert.id
        )
        assert alert.insight.query is not None
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

    @parameterized.expand(
        [
            (
                "subscription_failure",
                "products.alerts.backend.presentation.views.alert.AlertSubscription.objects.create",
                {"side_effect": RuntimeError},
            ),
            (
                "account_limit",
                "products.alerts.backend.models.alert.AlertConfiguration.check_alert_limit",
                {"return_value": "Alert limit reached"},
            ),
            (
                "invalid_detector",
                "products.alerts.backend.facade.onboarding.INGESTION_DETECTOR_CONFIG",
                {"new": {"type": "zscore", "window": 1}},
            ),
        ]
    )
    @patch("products.alerts.backend.facade.onboarding.capture_exception")
    @patch("products.alerts.backend.facade.onboarding.feature_enabled_or_false", return_value=True)
    @patch("products.alerts.backend.facade.onboarding.is_email_available", return_value=True)
    def test_alert_failure_does_not_block_project_creation(
        self,
        _name: str,
        target: str,
        options: dict,
        _mock_email: MagicMock,
        _mock_flag: MagicMock,
        _mock_capture: MagicMock,
    ) -> None:
        with patch(target, **options), self.captureOnCommitCallbacks(execute=True):
            team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)

        assert Team.objects.filter(id=team.id).exists()
        assert not AlertConfiguration.objects.filter(team_id=team.id).exists()
        assert not Insight.objects.filter(team_id=team.id, filters__default_ingestion_alert=True).exists()
        _mock_capture.assert_called_once()

    @patch("products.alerts.backend.facade.onboarding.feature_enabled_or_false", return_value=True)
    @patch("products.alerts.backend.facade.onboarding.is_email_available", return_value=True)
    def test_new_account_subscribes_creator_after_membership_exists(
        self, _mock_email: MagicMock, _mock_flag: MagicMock
    ) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            organization, team, user = User.objects.bootstrap(
                organization_name="Example organization",
                email="new-account@example.com",
                password=None,
            )
            assert not AlertConfiguration.objects.filter(team_id=team.id).exists()

        alert = AlertConfiguration.objects.get(team_id=team.id)
        assert user.organization_memberships.filter(organization=organization).exists()
        assert alert.created_by == user
        assert alert.get_subscribed_users_emails() == [user.email]


class TestEventVolumeAnomalies(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            ("increase", "UTC", 40, True),
            ("decrease", "UTC", 10, True),
            ("stop", "UTC", 0, True),
            ("usual_variation", "UTC", 21, False),
            ("small_increase", "UTC", 23, False),
            ("timezone", "America/New_York", 0, True),
        ]
    )
    @time_machine.travel("2026-10-19T12:00:00Z", tick=False)
    @patch("products.alerts.backend.facade.onboarding.feature_enabled_or_false", return_value=True)
    @patch("products.alerts.backend.facade.onboarding.is_email_available", return_value=True)
    def test_daily_event_volume_anomaly(
        self,
        _name: str,
        timezone: str,
        current_count: int,
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
        daily_counts = [(days_ago, 20 + (days_ago % 3 - 1) * 2) for days_ago in range(2, 17)]
        for days_ago, count in [*daily_counts, (1, current_count), (0, 100)]:
            event_at = datetime.combine(today - timedelta(days=days_ago), time(23), tzinfo=ZoneInfo(timezone))
            for _ in range(count):
                _create_event(
                    team=self.team,
                    event="example_event",
                    distinct_id="example-user",
                    timestamp=event_at.isoformat(),
                    created_at=datetime.now(UTC),
                )

        _create_event(
            team=self.team,
            event="old_event",
            distinct_id="example-user",
            timestamp=(datetime.now(UTC) - timedelta(days=90)).isoformat(),
            created_at=datetime.now(UTC),
        )

        assert alert.insight.query is not None
        assert alert.detector_config is not None
        extracted = extract_detector_series(
            alert.insight,
            self.team,
            TrendsQuery.model_validate(alert.insight.query["source"]),
            alert.detector_config,
            ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            user=self.user,
        )
        assert len(extracted.series) == 1
        series = extracted.series[0]
        assert series.points[series.current_index].value == current_count
        assert series.points[series.current_index].date == (today - timedelta(days=1)).isoformat()
        evaluation = evaluate_with_detector(extracted, alert.detector_config, insight=alert.insight, alert=alert)
        assert evaluation.value == current_count
        assert bool(evaluation.breaches) == expected_anomaly
