from typing import Optional

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseDestroyTablesMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from posthog.schema import AlertState, ChartDisplayType, EventsNode, TrendsFilter, TrendsFormulaNode, TrendsQuery

from posthog.api.test.dashboards import DashboardAPI
from posthog.models import AlertConfiguration
from posthog.models.alert import AlertCheck
from posthog.models.instance_setting import set_instance_setting
from posthog.tasks.alerts.checks import check_alert
from posthog.tasks.alerts.utils import send_notifications_for_breaches
from posthog.tasks.test.utils_email_tests import mock_email_messages


@freeze_time("2024-06-02T08:55:00.000Z")
@patch("posthog.tasks.alerts.checks.send_notifications_for_errors")
@patch("posthog.tasks.alerts.checks.send_notifications_for_breaches")
class TestAlertChecks(APIBaseTest, ClickhouseDestroyTablesMixin):
    def setUp(self) -> None:
        super().setUp()

        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)

        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

        query_dict = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                ),
            ],
            trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
        ).model_dump()

        self.insight = self.dashboard_api.create_insight(
            data={
                "name": "insight",
                "query": query_dict,
            }
        )[1]

        self.alert = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "alert name",
                "insight": self.insight["id"],
                "subscribed_users": [self.user.id],
                "calculation_interval": "daily",
                "config": {
                    "type": "TrendsAlertConfig",
                    "series_index": 0,
                },
                "condition": {"type": "absolute_value"},
                "threshold": {"configuration": {"type": "absolute", "bounds": {}}},
            },
        ).json()

    def set_thresholds(self, lower: Optional[int] = None, upper: Optional[int] = None) -> None:
        self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{self.alert['id']}",
            data={"threshold": {"configuration": {"type": "absolute", "bounds": {"lower": lower, "upper": upper}}}},
        )

    def skip_weekend(self, skip: bool) -> None:
        self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{self.alert['id']}",
            data={"skip_weekend": skip},
        )

    def get_breach_description(self, mock_send_notifications_for_breaches: MagicMock, call_index: int) -> list[str]:
        return mock_send_notifications_for_breaches.call_args_list[call_index].args[1]

    def test_alert_is_not_triggered_when_disabled(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=1)

        self.client.patch(f"/api/projects/{self.team.id}/alerts/{self.alert['id']}", data={"enabled": False})

        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 0

    def test_alert_is_triggered_for_values_above_higher_threshold(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(upper=0)

        with freeze_time("2024-06-02T07:55:00.000Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="1",
            )
            flush_persons_and_events()

        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        alert = mock_send_notifications_for_breaches.call_args_list[0].args[0]
        assert str(alert.id) == self.alert["id"]

        anomalies_descriptions = self.get_breach_description(mock_send_notifications_for_breaches, call_index=0)
        assert len(anomalies_descriptions) == 1
        assert (
            "The insight value ($pageview) for current interval (1) is more than upper threshold (0.0)"
            in anomalies_descriptions[0]
        )

    def test_alert_is_not_triggered_for_events_beyond_interval(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(upper=0)

        with freeze_time("2024-05-02T07:55:00.000Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="1",
            )
            flush_persons_and_events()

        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 0

    def test_alert_is_triggered_for_value_below_lower_threshold(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=1)

        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        anomalies = self.get_breach_description(mock_send_notifications_for_breaches, call_index=0)
        assert "The insight value ($pageview) for current interval (0) is less than lower threshold (1.0)" in anomalies

    def test_alert_triggers_but_does_not_send_notification_during_firing(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=1)

        # no events so this should fire
        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        alert = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at")
        assert alert.state == AlertState.FIRING

        with freeze_time("2024-06-02T09:00:00.000Z"):
            check_alert(self.alert["id"])

            assert mock_send_notifications_for_breaches.call_count == 1
            alert = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at")
            assert alert.state == AlertState.FIRING

        # move to next interval - next day
        with freeze_time("2024-06-03T09:55:00.000Z"):
            self.set_thresholds(lower=0)

            check_alert(self.alert["id"])

            assert mock_send_notifications_for_breaches.call_count == 1
            assert (
                AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at").state
                == AlertState.NOT_FIRING
            )

        with freeze_time("2024-06-04T11:00:00.000Z"):
            self.set_thresholds(lower=1)

            check_alert(self.alert["id"])

            assert mock_send_notifications_for_breaches.call_count == 2
            assert (
                AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at").state
                == AlertState.FIRING
            )

        # test clean up old checks (> 14 days)
        with freeze_time("2024-06-20T11:00:00.000Z"):
            AlertCheck.clean_up_old_checks()
            assert AlertCheck.objects.filter(alert_configuration=self.alert["id"]).count() == 0

    def test_alert_is_set_to_not_firing_when_disabled(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=1)

        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        assert (
            AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at").state
            == AlertState.FIRING
        )

        self.client.patch(f"/api/projects/{self.team.id}/alerts/{self.alert['id']}", data={"enabled": False})

        # Check that the alert is set to inactive and checks are not triggered
        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        assert AlertConfiguration.objects.get(pk=self.alert["id"]).state == AlertState.NOT_FIRING

    def test_alert_is_set_to_not_firing_when_threshold_changes(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=1)

        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        assert (
            AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at").state
            == AlertState.FIRING
        )

        self.set_thresholds(lower=2)

        assert AlertConfiguration.objects.get(pk=self.alert["id"]).state == AlertState.NOT_FIRING

    def test_alert_is_not_triggered_for_normal_values(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=0, upper=1)

        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 0

    def test_send_error_while_calculating(
        self, _mock_send_notifications_for_breaches: MagicMock, mock_send_notifications_for_errors: MagicMock
    ) -> None:
        with patch(
            "posthog.tasks.alerts.trends.calculate_for_query_based_insight"
        ) as mock_calculate_for_query_based_insight:
            mock_calculate_for_query_based_insight.side_effect = Exception("Some error")

            with freeze_time("2024-06-02T09:00:00.000Z"):
                check_alert(self.alert["id"])
                assert mock_send_notifications_for_errors.call_count == 1

                latest_alert_check = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest(
                    "created_at"
                )

                error_message = latest_alert_check.error["message"]
                assert "Some error" in error_message

    def test_error_while_calculating_on_alert_in_firing_state(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_notifications_for_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=1)
        check_alert(self.alert["id"])
        assert mock_send_notifications_for_breaches.call_count == 1
        assert mock_send_notifications_for_errors.call_count == 0

        latest_alert_check = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at")
        assert latest_alert_check.state == AlertState.FIRING
        assert latest_alert_check.error is None

        with patch(
            "posthog.tasks.alerts.trends.calculate_for_query_based_insight"
        ) as mock_calculate_for_query_based_insight:
            mock_calculate_for_query_based_insight.side_effect = Exception("Some error")

            with freeze_time("2024-06-03T09:00:00.000Z"):
                check_alert(self.alert["id"])
                assert mock_send_notifications_for_breaches.call_count == 1
                assert mock_send_notifications_for_errors.call_count == 1

                latest_alert_check = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest(
                    "created_at"
                )
                assert latest_alert_check.state == AlertState.ERRORED

                error_message = latest_alert_check.error["message"]
                assert "Some error" in error_message

    def test_error_while_calculating_on_alert_in_not_firing_state(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_notifications_for_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=0)
        check_alert(self.alert["id"])
        assert mock_send_notifications_for_breaches.call_count == 0
        assert mock_send_notifications_for_errors.call_count == 0

        latest_alert_check = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at")
        assert latest_alert_check.state == AlertState.NOT_FIRING
        assert latest_alert_check.error is None

        with patch(
            "posthog.tasks.alerts.trends.calculate_for_query_based_insight"
        ) as mock_calculate_for_query_based_insight:
            mock_calculate_for_query_based_insight.side_effect = Exception("Some error")

            with freeze_time("2024-06-03T09:00:00.000Z"):
                check_alert(self.alert["id"])
                assert mock_send_notifications_for_breaches.call_count == 0
                assert mock_send_notifications_for_errors.call_count == 1

                latest_alert_check = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest(
                    "created_at"
                )

                error_message = latest_alert_check.error["message"]
                assert "Some error" in error_message

    def test_alert_with_insight_with_filter(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.dashboard_api.create_insight(
            data={"name": "insight", "filters": {"events": [{"id": "$pageview"}], "display": "BoldNumber"}}
        )[1]

        self.client.patch(f"/api/projects/{self.team.id}/alerts/{self.alert['id']}", data={"insight": insight["id"]})
        self.set_thresholds(lower=1)

        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        anomalies = self.get_breach_description(mock_send_notifications_for_breaches, call_index=0)
        assert "The insight value ($pageview) for current interval (0) is less than lower threshold (1.0)" in anomalies

    @patch("posthog.tasks.alerts.utils.EmailMessage")
    def test_send_emails(
        self, MockEmailMessage: MagicMock, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        alert = AlertConfiguration.objects.get(pk=self.alert["id"])
        send_notifications_for_breaches(alert, ["first anomaly description", "second anomaly description"])

        assert len(mocked_email_messages) == 1
        email = mocked_email_messages[0]
        assert len(email.to) == 1
        assert email.to[0]["recipient"] == "user1@posthog.com"
        assert "first anomaly description" in email.html_body
        assert "second anomaly description" in email.html_body

    def test_alert_not_recalculated_when_not_due(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=1)

        # no events so this should fire
        check_alert(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        alert = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at")
        assert alert.state == AlertState.FIRING

        with freeze_time("2024-06-02T09:00:00.000Z"):
            check_alert(self.alert["id"])

            assert mock_send_notifications_for_breaches.call_count == 1
            check = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at")
            assert check.state == AlertState.FIRING

        # same day for daily alert so won't recalculate as haven't passed next_check_at
        with freeze_time("2024-06-02T09:55:00.000Z"):
            check_alert(self.alert["id"])

            second_check = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at")
            # didn't recalculate alert as it was not due
            assert check.id == second_check.id

    def test_alert_not_recalculated_when_is_calculating(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=1)

        alert = AlertConfiguration.objects.get(pk=self.alert["id"])
        assert alert.is_calculating is False

        # no events so this should fire
        check_alert(self.alert["id"])

        # False after check finished
        alert = AlertConfiguration.objects.get(pk=self.alert["id"])
        assert alert.is_calculating is False
        assert mock_send_notifications_for_breaches.call_count == 1
        first_check = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at")

        alert.next_check_at = None
        alert.is_calculating = True
        alert.save()

        check_alert(self.alert["id"])

        # should not have recalculated
        assert mock_send_notifications_for_breaches.call_count == 1
        second_check = AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at")
        assert first_check.id == second_check.id

    def test_alert_is_not_checked_on_weekend_when_skip_weekends_is_true(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.skip_weekend(True)

        # run on weekend
        with freeze_time("2024-12-21T07:55:00.000Z"):
            check_alert(self.alert["id"])

        checks = AlertCheck.objects.filter(alert_configuration=self.alert["id"])
        assert len(checks) == 0

    def test_alert_is_checked_on_weekday_when_skip_weekends_is_true(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.skip_weekend(True)

        # run on week day
        with freeze_time("2024-12-19T07:55:00.000Z"):
            check_alert(self.alert["id"])

        checks = AlertCheck.objects.filter(alert_configuration=self.alert["id"])
        assert len(checks) == 1

    def test_alert_triggered_for_single_formula(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        query_dict = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                    custom_name="A",
                ),
            ],
            trendsFilter=TrendsFilter(
                display=ChartDisplayType.BOLD_NUMBER,
                formulaNodes=[TrendsFormulaNode(formula="A*2", custom_name="Double Pageviews")],
            ),
        ).model_dump()

        insight = self.dashboard_api.create_insight(
            data={
                "name": "formula insight",
                "query": query_dict,
            }
        )[1]

        alert_data = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "formula alert",
                "insight": insight["id"],
                "subscribed_users": [self.user.id],
                "calculation_interval": "daily",
                "config": {
                    "type": "TrendsAlertConfig",
                    "series_index": 0,  # Target the first (only) formula
                },
                "condition": {"type": "absolute_value"},
                "threshold": {"configuration": {"type": "absolute", "bounds": {"upper": 1}}},  # Threshold is 1
            },
        ).json()

        # Create 1 event, formula A*2 = 2, which is > 1
        with freeze_time("2024-06-02T07:55:00.000Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="1",
            )
            flush_persons_and_events()

        check_alert(alert_data["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        alert_config = mock_send_notifications_for_breaches.call_args_list[0].args[0]
        assert str(alert_config.id) == alert_data["id"]

        anomalies_descriptions = self.get_breach_description(mock_send_notifications_for_breaches, call_index=0)
        assert len(anomalies_descriptions) == 1
        assert (
            "The insight value (Double Pageviews) for current interval (2.0) is more than upper threshold (1.0)"
            in anomalies_descriptions[0]
        )

    def test_alert_triggered_for_legacy_formulas(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        query_dict = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                    custom_name="A",
                ),
            ],
            trendsFilter=TrendsFilter(
                display=ChartDisplayType.BOLD_NUMBER,
                formulas=["A*2"],
            ),
        ).model_dump()

        insight = self.dashboard_api.create_insight(
            data={
                "name": "formula insight",
                "query": query_dict,
            }
        )[1]

        alert_data = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "formula alert",
                "insight": insight["id"],
                "subscribed_users": [self.user.id],
                "calculation_interval": "daily",
                "config": {
                    "type": "TrendsAlertConfig",
                    "series_index": 0,  # Target the first (only) formula
                },
                "condition": {"type": "absolute_value"},
                "threshold": {"configuration": {"type": "absolute", "bounds": {"upper": 1}}},  # Threshold is 1
            },
        ).json()

        # Create 1 event, formula A*2 = 2, which is > 1
        with freeze_time("2024-06-02T07:55:00.000Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="1",
            )
            flush_persons_and_events()

        check_alert(alert_data["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        alert_config = mock_send_notifications_for_breaches.call_args_list[0].args[0]
        assert str(alert_config.id) == alert_data["id"]

        anomalies_descriptions = self.get_breach_description(mock_send_notifications_for_breaches, call_index=0)
        assert len(anomalies_descriptions) == 1
        assert (
            "The insight value (Formula (A*2)) for current interval (2.0) is more than upper threshold (1.0)"
            in anomalies_descriptions[0]
        )

    def test_alert_triggered_for_legacy_formula(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        query_dict = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                    custom_name="A",
                ),
            ],
            trendsFilter=TrendsFilter(
                display=ChartDisplayType.BOLD_NUMBER,
                formula="A*2",
            ),
        ).model_dump()

        insight = self.dashboard_api.create_insight(
            data={
                "name": "formula insight",
                "query": query_dict,
            }
        )[1]

        alert_data = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "formula alert",
                "insight": insight["id"],
                "subscribed_users": [self.user.id],
                "calculation_interval": "daily",
                "config": {
                    "type": "TrendsAlertConfig",
                    "series_index": 0,  # Target the first (only) formula
                },
                "condition": {"type": "absolute_value"},
                "threshold": {"configuration": {"type": "absolute", "bounds": {"upper": 1}}},  # Threshold is 1
            },
        ).json()

        # Create 1 event, formula A*2 = 2, which is > 1
        with freeze_time("2024-06-02T07:55:00.000Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="1",
            )
            flush_persons_and_events()

        check_alert(alert_data["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        alert_config = mock_send_notifications_for_breaches.call_args_list[0].args[0]
        assert str(alert_config.id) == alert_data["id"]

        anomalies_descriptions = self.get_breach_description(mock_send_notifications_for_breaches, call_index=0)
        assert len(anomalies_descriptions) == 1
        assert (
            "The insight value (Formula (A*2)) for current interval (2.0) is more than upper threshold (1.0)"
            in anomalies_descriptions[0]
        )

    def test_alert_triggered_for_second_formula(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        query_dict = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                    custom_name="A",
                ),
            ],
            trendsFilter=TrendsFilter(
                display=ChartDisplayType.BOLD_NUMBER,
                formulaNodes=[
                    TrendsFormulaNode(formula="A", custom_name="Raw Pageviews"),
                    TrendsFormulaNode(formula="A*2", custom_name="Double Pageviews"),
                ],
            ),
        ).model_dump()

        insight = self.dashboard_api.create_insight(
            data={
                "name": "multi formula insight",
                "query": query_dict,
            }
        )[1]

        alert_data = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "multi formula alert",
                "insight": insight["id"],
                "subscribed_users": [self.user.id],
                "calculation_interval": "daily",
                "config": {
                    "type": "TrendsAlertConfig",
                    "series_index": 1,  # Target the second formula (A*2)
                },
                "condition": {"type": "absolute_value"},
                "threshold": {"configuration": {"type": "absolute", "bounds": {"upper": 1}}},  # Threshold is 1
            },
        ).json()

        # Create 1 event.
        # Formula 1 (A) = 1, which is <= 1 (no breach)
        # Formula 2 (A*2) = 2, which is > 1 (breach)
        with freeze_time("2024-06-02T07:55:00.000Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="1",
            )
            flush_persons_and_events()

        check_alert(alert_data["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        alert_config = mock_send_notifications_for_breaches.call_args_list[0].args[0]
        assert str(alert_config.id) == alert_data["id"]

        anomalies_descriptions = self.get_breach_description(mock_send_notifications_for_breaches, call_index=0)
        assert len(anomalies_descriptions) == 1

        # Check the breach message refers to the correct formula (Double Pageviews) and value (2)
        assert (
            "The insight value (Double Pageviews) for current interval (2.0) is more than upper threshold (1.0)"
            in anomalies_descriptions[0]
        )
