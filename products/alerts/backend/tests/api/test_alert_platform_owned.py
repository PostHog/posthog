from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.scoping import team_scope
from posthog.schema_enums import AlertCalculationInterval

from products.alerts.backend.evaluation.detector import _earlier_flags
from products.alerts.backend.facade.api import snooze_alert_from_slack
from products.alerts.backend.facade.contracts import PlatformCannotOwn
from products.alerts.backend.judge import (
    LLM_DETECTOR_UNAVAILABLE_ERROR_CODE,
    LLM_DETECTOR_UNAVAILABLE_MESSAGE,
    EarlierFlag,
)
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.alerts.backend.platform_cutover import cut_over_team
from products.alerts.backend.test.insight_alerts import create_insight_alert
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import get_configuration, update_configuration
from products.alerts_platform.backend.facade.contracts import (
    InvalidPlatformAlertEdit,
    PlatformAlertConfigurationEdit,
    SourceKind,
)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


class TestPlatformOwnedInsightAlert(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.now = datetime.now(UTC)
        self.alert = create_insight_alert(
            self.team,
            next_check_at=self.now + timedelta(minutes=3),
            last_checked_at=self.now - timedelta(hours=2),
        )
        AlertCheck.objects.create(alert_configuration=self.alert, calculated_value=1.0, state="Not firing")
        [cutover] = cut_over_team(self.team.id, now=self.now)
        assert cutover.skipped is None
        with team_scope(self.team.id):
            self.copy_id = platform_testing.copy_of(self.alert.id).id
        self.url = f"/api/projects/{self.team.id}/alerts"

    def _at(self, minutes_ago: int) -> datetime:
        return self.now - timedelta(minutes=minutes_ago)

    def _record(
        self,
        minutes_ago: int,
        state: str,
        *,
        value: float | None = None,
        error: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        platform_testing.record_check(
            self.copy_id,
            team_id=self.team.id,
            at=self._at(minutes_ago),
            previous_state="not_firing",
            state=state,
            value=value,
            error_message=error,
            source_detail=detail,
        )

    def _own_check(self, minutes_ago: int, date: str, rationale: str) -> None:
        check = AlertCheck.objects.create(
            alert_configuration=self.alert,
            state="Firing",
            triggered_points=[9],
            triggered_dates=[date],
            triggered_metadata={"detector_type": "llm", "rationale": rationale},
        )
        AlertCheck.objects.filter(id=check.id).update(created_at=self._at(minutes_ago))

    def _row(self, action: str, query: str = "") -> dict[str, Any]:
        if action == "list":
            response = self.client.get(f"{self.url}/")
            assert response.status_code == status.HTTP_200_OK
            [row] = response.json()["results"]
            return row
        response = self.client.get(f"{self.url}/{self.alert.id}/{query}")
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    @parameterized.expand([("list",), ("retrieve",)])
    def test_a_moved_alert_shows_the_platform_state_and_last_check(self, action: str) -> None:
        self._record(30, "firing", value=150.0)
        with team_scope(self.team.id):
            platform_testing.start_firing(self.copy_id, team_id=self.team.id, at=self._at(30))

        row = self._row(action)

        assert (row["state"], row["last_checked_at"], row["last_value"]) == ("Firing", _iso(self._at(30)), 150.0)

    def test_a_moved_alert_lists_its_checks_from_the_platform(self) -> None:
        self._record(90, "not_firing", value=50.0)
        self._record(60, "firing", value=150.0)
        self._record(30, "errored", error="Query timed out")
        # A snoozed check evaluates nothing, so it measures no value either.
        self._record(15, "snoozed")

        row = self._row("retrieve", "?checks_limit=2")

        assert row["checks_total"] == 4
        assert [(check["created_at"], check["state"], check["calculated_value"]) for check in row["checks"]] == [
            (_iso(self._at(15)), "Snoozed", None),
            (_iso(self._at(30)), "Errored", None),
        ]
        # The newest check measured nothing, so an older check's value must not stand in for it.
        assert row["last_value"] is None
        # A platform error can carry an internal detail, so the history shows the generic message.
        assert row["checks"][1]["error"] == {
            "message": "This alert encountered an error. Check the alert configuration and try again."
        }
        past_the_end = self._row("retrieve", "?checks_offset=5")
        assert (past_the_end["checks_total"], past_the_end["checks"]) == (4, [])
        # A check made at the window's end, to the microsecond, is inside it.
        up_to_a_check = self._row("retrieve", f"?checks_date_to={_iso(self._at(60))}")
        assert [check["created_at"] for check in up_to_a_check["checks"]] == [_iso(self._at(60)), _iso(self._at(90))]

    def test_a_moved_detector_alert_shows_its_detector_output_from_the_platform(self) -> None:
        detail = {
            "anomaly_scores": [0.99],
            "triggered_points": [9],
            "triggered_dates": ["2026-10-20"],
            "interval": "day",
            "triggered_metadata": {"detector_type": "llm", "rationale": "Signups fell.", "kind": "drop"},
        }
        self._record(30, "firing", value=150.0, detail=detail)
        # History outlives the code that wrote it, so a value of another shape is left out.
        self._record(20, "firing", value=150.0, detail={**detail, "triggered_dates": "2026-10-21"})

        # The history explains a check the model could not answer, as it does for the alert's own checks.
        self._record(
            10,
            "errored",
            error=LLM_DETECTOR_UNAVAILABLE_MESSAGE,
            detail={"error_code": LLM_DETECTOR_UNAVAILABLE_ERROR_CODE},
        )

        unanswered, newest, oldest = self._row("retrieve", "?checks_limit=3")["checks"]

        assert {key: oldest[key] for key in detail} == detail
        assert newest["triggered_dates"] is None
        assert unanswered["error"] == {
            "code": LLM_DETECTOR_UNAVAILABLE_ERROR_CODE,
            "message": LLM_DETECTOR_UNAVAILABLE_MESSAGE,
        }

    def test_a_moved_detector_alert_marks_the_points_both_stacks_fired_on(self) -> None:
        self._own_check(60 * 24, "2026-10-18", "Before the move.")
        # The shadow's check after the move sent nothing, so the platform's verdict replaces it.
        self._own_check(-30, "2026-10-19", "The shadow.")
        # Before the move, the platform's copy only ran in parallel, so its verdicts are not the alert's.
        self._record(60, "firing", detail={"triggered_points": [9], "triggered_dates": ["2026-10-17"]})
        self._record(-30, "firing", detail={"triggered_points": [9], "triggered_dates": ["2026-10-20"]})
        self._record(-20, "not_firing", detail={"anomaly_scores": [0.1]})

        row = self._row("list")

        assert [check["triggered_dates"] for check in row["checks"]] == [["2026-10-20"], ["2026-10-18"]]

    @parameterized.expand(
        [
            ("every_check", 500, ["2026-10-18", "2026-10-20"]),
            # A newer statistical check must not use up the limit and push out the AI verdict.
            ("only_the_newest", 1, ["2026-10-20"]),
        ]
    )
    def test_a_moved_ai_alert_reads_its_earlier_flags_from_both_stacks(
        self, _name: str, limit: int, dates: list[str]
    ) -> None:
        self._own_check(60 * 24, "2026-10-18", "Before the move.")
        self._own_check(-30, "2026-10-19", "The shadow.")
        llm = {"detector_type": "llm"}
        # Before the move, the platform's copy only ran in parallel, so its verdicts are not the alert's.
        self._record(60, "firing", detail={"triggered_dates": ["2026-10-17"], "triggered_metadata": llm})
        self._record(
            -30,
            "firing",
            detail={"triggered_dates": ["2026-10-20"], "triggered_metadata": {**llm, "rationale": "After."}},
        )
        self._record(
            -25, "firing", detail={"triggered_dates": ["2026-10-21"], "triggered_metadata": {"detector_type": "zscore"}}
        )
        self._record(
            -20, "errored", error="boom", detail={"triggered_dates": ["2026-10-22"], "triggered_metadata": llm}
        )
        self.alert.refresh_from_db()

        with patch("products.alerts.backend.evaluation.detector.MAX_EARLIER_CHECKS", limit):
            flags = _earlier_flags(self.alert)

        reasons = {"2026-10-18": "Before the move.", "2026-10-20": "After."}
        assert flags == tuple(EarlierFlag(date=date, rationale=reasons[date]) for date in dates)

    def test_a_platform_history_failure_falls_back_to_the_alerts_own_checks(self) -> None:
        self._record(30, "firing", value=150.0)

        with patch(
            "products.alerts.backend.platform_alert_reads.check_page_by_legacy_id",
            side_effect=RuntimeError("ClickHouse is down"),
        ):
            row = self._row("retrieve")

        assert [(check["state"], check["calculated_value"]) for check in row["checks"]] == [("Not firing", 1.0)]


class TestPlatformOwnedInsightAlertWrites(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.now = datetime.now(UTC)
        self.alert = create_insight_alert(self.team, next_check_at=self.now + timedelta(minutes=3))
        [cutover] = cut_over_team(self.team.id, now=self.now)
        assert cutover.skipped is None
        with team_scope(self.team.id):
            self.copy_id = platform_testing.copy_of(self.alert.id).id
        self.url = f"/api/projects/{self.team.id}/alerts"

    def _copy(self) -> Any:
        with team_scope(self.team.id):
            view = get_configuration(
                team_id=self.team.id, source_kinds=[SourceKind.INSIGHT.value], configuration_id=self.copy_id
            )
        assert view is not None
        return view

    def _edit_on_the_platform(
        self, change: Callable[[PlatformAlertConfigurationEdit], PlatformAlertConfigurationEdit]
    ) -> None:
        # The platform API does not serve insight copies yet, so this calls the edit it would make.
        with team_scope(self.team.id):
            update_configuration(
                team_id=self.team.id,
                source_kinds=[SourceKind.INSIGHT.value],
                configuration_id=self.copy_id,
                change=change,
            )

    def test_each_api_writes_both_rows_of_an_alert_the_platform_owns(self) -> None:
        self._edit_on_the_platform(lambda stored: replace(stored, name="Edited on the platform"))
        insight_edit = self.client.patch(
            f"{self.url}/{self.alert.id}/",
            {"threshold": {"configuration": {"type": "absolute", "bounds": {"upper": 200}}}},
            format="json",
        )

        assert insight_edit.status_code == status.HTTP_200_OK, insight_edit.json()
        assert insight_edit.json()["name"] == "Edited on the platform"
        copy = self._copy()
        assert (copy.name, copy.source_config["condition"]["threshold"]["bounds"]) == (
            "Edited on the platform",
            {"upper": 200},
        )

    @parameterized.expand(
        [
            ("percentage_bound", {"threshold": {"type": "percentage", "bounds": {"upper": 0.5}}}),
            # The insight API checks a detector against its insight and its access rules, so only it may set one.
            ("detector", {"detector": {"type": "zscore"}}),
        ]
    )
    def test_a_platform_edit_the_insight_stack_cannot_check_is_refused_on_both_rows(
        self, _name: str, condition_change: dict[str, Any]
    ) -> None:
        stored_config = self._copy().source_config

        def edit(stored: PlatformAlertConfigurationEdit) -> PlatformAlertConfigurationEdit:
            condition = {**stored.source_config["condition"], **condition_change}
            return replace(stored, source_config={**stored.source_config, "condition": condition})

        with pytest.raises(InvalidPlatformAlertEdit):
            self._edit_on_the_platform(edit)

        self.alert.refresh_from_db()
        assert self.alert.threshold is not None
        assert (self.alert.threshold.configuration["type"], self.alert.detector_config) == ("absolute", None)
        assert self._copy().source_config == stored_config

    def test_a_platform_edit_cannot_turn_an_ai_alert_back_on(self) -> None:
        self._edit_on_the_platform(lambda stored: replace(stored, enabled=False))
        AlertConfiguration.objects.filter(id=self.alert.id).update(detector_config={"type": "llm"})

        with pytest.raises(InvalidPlatformAlertEdit) as refused:
            self._edit_on_the_platform(lambda stored: replace(stored, enabled=True))

        assert refused.value.field_name == "enabled"
        self.alert.refresh_from_db()
        assert (self.alert.enabled, self._copy().enabled) == (False, False)

    def test_a_snooze_from_slack_mutes_the_platform_copy(self) -> None:
        outcome = snooze_alert_from_slack(self.alert.id, user=self.user, duration="1d")

        assert outcome == "snoozed"
        self.alert.refresh_from_db()
        assert self.alert.snoozed_until is not None
        assert self._copy().snooze_until == self.alert.snoozed_until

    def test_a_snooze_the_platform_refuses_leaves_both_rows_unsnoozed(self) -> None:
        with patch(
            "products.alerts.backend.platform_ownership.on_updated",
            side_effect=PlatformCannotOwn("The alerts platform cannot run this alert."),
        ):
            outcome = snooze_alert_from_slack(self.alert.id, user=self.user, duration="1d")

        assert outcome == "not_snoozable"
        self.alert.refresh_from_db()
        assert (self.alert.snoozed_until, self._copy().snooze_until) == (None, None)

    def test_an_edit_the_platform_cannot_run_is_refused_on_both_rows(self) -> None:
        # Real-time passes the insight API's own checks on this insight, so only the platform refuses it.
        self.organization.available_product_features = [
            {"key": AvailableFeature.REAL_TIME_ALERTS, "name": "Real-time alerts"}
        ]
        self.organization.save()

        response = self.client.patch(
            f"{self.url}/{self.alert.id}/",
            {"calculation_interval": AlertCalculationInterval.REAL_TIME.value},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "alerts platform" in str(response.json())
        self.alert.refresh_from_db()
        assert self.alert.calculation_interval == AlertCalculationInterval.DAILY.value

    @parameterized.expand([("a_team_on_the_platform", True), ("a_team_off_the_platform", False)])
    def test_a_new_alert_is_handed_over_only_in_a_team_on_the_platform(self, _name: str, begun: bool) -> None:
        if not begun:
            AlertConfiguration.objects.filter(id=self.alert.id).update(owner="source")
        insight = create_insight_alert(self.team).insight

        response = self.client.post(
            f"{self.url}",
            {
                "insight": insight.id,
                "subscribed_users": [self.user.id],
                "condition": {"type": "absolute_value"},
                "config": {"type": "TrendsAlertConfig", "series_index": 0},
                "name": "A new alert",
                "threshold": {"configuration": {"type": "absolute", "bounds": {"upper": 100}}},
                "calculation_interval": "daily",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        created = AlertConfiguration.objects.get(id=response.json()["id"])
        assert created.owner == ("platform" if begun else "source")

    def test_deleting_a_moved_alert_deletes_its_copy(self) -> None:
        response = self.client.delete(f"{self.url}/{self.alert.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        with team_scope(self.team.id):
            assert (
                get_configuration(
                    team_id=self.team.id, source_kinds=[SourceKind.INSIGHT.value], configuration_id=self.copy_id
                )
                is None
            )
