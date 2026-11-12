from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.schema import InsightThreshold

from posthog.constants import AvailableFeature
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.scoping import team_scope
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.user import User
from posthog.schema_enums import AlertCalculationInterval, AlertState

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.alerts.backend.evaluation.detector import _earlier_flags, _saved_alert_flags
from products.alerts.backend.facade.api import (
    WATCHED_ROWS_PER_INSIGHT,
    enabled_alert_insight_ids,
    first_subscriber_id,
    get_alert_team_id,
    insight_ids_with_alerts,
    insight_ids_with_enabled_alerts,
    insight_short_ids_watched_by,
    list_enabled_alerts,
    list_errored_alerts,
    list_firing_alerts_created_by,
    snooze_alert_from_slack,
)
from products.alerts.backend.facade.contracts import PlatformCannotOwn
from products.alerts.backend.judge import (
    LLM_DETECTOR_UNAVAILABLE_ERROR_CODE,
    LLM_DETECTOR_UNAVAILABLE_MESSAGE,
    EarlierFlag,
)
from products.alerts.backend.llm_detector_limits import count_enabled_llm_alerts
from products.alerts.backend.models.alert import (
    AlertCheck,
    AlertConfiguration,
    AlertSubscription,
    InvestigationStatus,
    InvestigationVerdict,
    Threshold,
)
from products.alerts.backend.models.investigation import InsightAlertInvestigation
from products.alerts.backend.platform_cutover import cut_over_team
from products.alerts.backend.platform_insight_alert import native_insight_alert_view
from products.alerts.backend.platform_investigation_detail import SUPPRESSED_BY_AGENT_KEY
from products.alerts.backend.platform_native_cleanup import NativeCleanupInputs, delete_native_alert, native_alert_ids
from products.alerts.backend.platform_subscribers import SUBSCRIBER_EVENT_KINDS
from products.alerts.backend.presentation.views.alert import AlertViewSet
from products.alerts.backend.tasks.tasks import remove_departed_subscriber
from products.alerts.backend.test.insight_alerts import create_insight_alert
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import (
    assign_native_creator,
    get_configuration,
    list_alert_destinations,
    record_verdict_change,
    set_subscriber_destinations,
    subscriber_user_ids_by_public_id,
    update_configuration,
)
from products.alerts_platform.backend.facade.contracts import (
    SOURCE_CONDITION_KEY,
    AlertDelivery,
    DestinationType,
    InvalidPlatformAlertEdit,
    PlatformAlertConfigurationEdit,
    PlatformAlertConfigurationView,
    SourceKind,
    VerdictChange,
)
from products.alerts_platform.backend.facade.enums import HoldRelease, HoldReleasedBy, PlatformAlertOwner
from products.alerts_platform.backend.facade.scheduling import REAL_TIME_CADENCE_MINUTES
from products.cdp.backend.facade.models import HogFunction
from products.cdp.backend.templates.fixtures import template_slack
from products.cdp.backend.templates.hog_function_template import sync_template_to_db
from products.notebooks.backend.facade.api import create_notebook
from products.product_analytics.backend.facade.models import Insight


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

    def _follow_up(self, minutes_ago: int, *, firing_minutes_ago: int) -> None:
        firing_at = self._at(firing_minutes_ago)
        with team_scope(self.team.id):
            platform_testing.start_firing(self.copy_id, team_id=self.team.id, at=firing_at)
            request = record_verdict_change(
                VerdictChange(
                    team_id=self.team.id,
                    configuration_id=self.copy_id,
                    firing_evaluation_key=f"slot:{firing_at.isoformat()}",
                    episode_started_at=firing_at,
                    firing_event_id="$insight_alert_firing",
                ),
                now=self._at(minutes_ago),
            )
        assert request is not None

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
        self._follow_up(10, firing_minutes_ago=30)

        row = self._row(action)

        assert (row["state"], row["last_checked_at"], row["last_value"]) == ("Firing", _iso(self._at(30)), 150.0)

    def test_a_moved_alert_lists_its_checks_from_the_platform(self) -> None:
        self._record(90, "not_firing", value=50.0)
        self._record(60, "firing", value=150.0)
        self._record(30, "errored", error="Query timed out")
        # A snoozed check evaluates nothing, so it measures no value either.
        self._record(15, "snoozed")
        self._follow_up(10, firing_minutes_ago=60)

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

    def test_a_moved_alert_shows_each_checks_investigation_and_what_the_agent_suppressed(self) -> None:
        notebook = create_notebook(self.team.id, title="Signups investigation", content=None)
        for minutes_ago in (40, 30, 20, 10):
            self._record(
                minutes_ago,
                "firing",
                value=150.0,
                detail={SUPPRESSED_BY_AGENT_KEY: True} if minutes_ago == 10 else None,
            )
        InsightAlertInvestigation.objects.for_team(self.team.id).create(
            team=self.team,
            alert_configuration=self.alert,
            configuration_id=self.copy_id,
            evaluation_key=f"slot:{self._at(40).isoformat()}",
            kind=InsightAlertInvestigation.Kind.AGENT,
            status=InvestigationStatus.DONE,
            verdict=InvestigationVerdict.FALSE_POSITIVE,
            summary="A release changed the event name.",
            notebook_id=notebook.id,
        )
        released = [
            (40, HoldReleasedBy.VERDICT),
            (30, HoldReleasedBy.SAFETY_NET),
            (20, HoldReleasedBy.CLAIM_REFUSED),
        ]
        for minutes_ago, released_by in released:
            platform_testing.released_hold(
                self.copy_id,
                team_id=self.team.id,
                at=self._at(minutes_ago),
                action=HoldRelease.SUPPRESS,
                released_by=released_by,
            )

        checks = self._row("retrieve")["checks"]

        fields = (
            "investigation_status",
            "investigation_verdict",
            "investigation_summary",
            "investigation_notebook_short_id",
            "notification_suppressed_by_agent",
        )
        assert [tuple(check[field] for field in fields) for check in checks] == [
            (None, None, None, None, True),
            (None, None, None, None, True),
            (None, None, None, None, False),
            ("done", "false_positive", "A release changed the event name.", notebook.short_id, True),
        ]

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

    def test_simulating_an_ai_alert_insight_keeps_no_row_for_reads_its_earlier_flags_from_the_platform(self) -> None:
        with team_scope(self.team.id):
            platform_testing.forget_source_row(self.copy_id)
        AlertConfiguration.objects.filter(id=self.alert.id).delete()
        self._record(
            -30,
            "firing",
            detail={
                "triggered_dates": ["2026-10-20"],
                "triggered_metadata": {"detector_type": "llm", "rationale": "Fell."},
            },
        )

        flags = _saved_alert_flags(self.team, self.copy_id)

        assert flags == (EarlierFlag(date="2026-10-20", rationale="Fell."),)

    def test_an_alert_insight_keeps_no_row_for_shows_from_the_platform(self) -> None:
        threshold = self.alert.threshold
        assert threshold is not None
        scheduled = self.client.patch(f"{self.url}/{self.alert.id}/", {"schedule_start_time": "09:30"}, format="json")
        assert scheduled.status_code == status.HTTP_200_OK, scheduled.json()
        with team_scope(self.team.id):
            platform_testing.forget_source_row(self.copy_id)
            platform_testing.start_firing(self.copy_id, team_id=self.team.id, at=self._at(30))
        AlertConfiguration.objects.filter(id=self.alert.id).delete()
        self._record(30, "firing", value=150.0)
        self._record(20, "firing", value=160.0)
        platform_testing.released_hold(
            self.copy_id,
            team_id=self.team.id,
            at=self._at(30),
            action=HoldRelease.SUPPRESS,
            released_by=HoldReleasedBy.VERDICT,
        )

        response = self.client.get(f"{self.url}/{self.copy_id}/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        row = response.json()
        assert (row["id"], row["insight"]["id"], row["threshold"]["configuration"]) == (
            str(self.copy_id),
            self.alert.insight_id,
            threshold.configuration,
        )
        assert (row["state"], row["last_value"], row["checks_total"]) == ("Firing", 160.0, 2)
        assert (row["schedule_start_time"], row["threshold"]["created_at"] is not None) == ("09:30", True)
        assert row["threshold"]["id"] == str(self.copy_id)
        assert [check["notification_suppressed_by_agent"] for check in row["checks"]] == [False, True]
        assert not AlertConfiguration.objects.filter(team=self.team).exists()
        # An alert with no insight row passes the same insight access gate as one with a row.
        with patch(
            "products.access_control.backend.facade.user_access_control.UserAccessControl.filter_queryset_by_access_level",
            side_effect=lambda queryset, *args, **kwargs: queryset.none(),
        ):
            hidden = self.client.get(f"{self.url}/{self.copy_id}/")
        assert hidden.status_code == status.HTTP_404_NOT_FOUND

    def test_a_detector_alert_insight_keeps_no_row_for_shows_a_threshold_the_schema_accepts(self) -> None:
        with team_scope(self.team.id):
            native = platform_testing.create_configuration(
                team_id=self.team.id,
                name="detector",
                source_kind="insight",
                source_config={"insight_id": self.alert.insight_id, "condition": {"detector": {"type": "zscore"}}},
                check_interval_minutes=1440,
                owner="platform",
                legacy_configuration_id=None,
            )

        response = self.client.get(f"{self.url}/{native.id}/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        InsightThreshold.model_validate(response.json()["threshold"]["configuration"])

    @parameterized.expand(
        [
            ("everything", "", ["native", "row"]),
            ("other_insight", "insight_id={row_insight}", ["row"]),
            ("search_finds_a_native_name", "search=alert", ["native"]),
            ("detector_alerts_only", "has_detector=true", ["row"]),
        ]
    )
    def test_the_list_merges_alerts_insight_keeps_no_row_for_with_rows(
        self, _name: str, query: str, expected: list[str]
    ) -> None:
        with team_scope(self.team.id):
            platform_testing.forget_source_row(self.copy_id)
        AlertConfiguration.objects.filter(id=self.alert.id).delete()
        row = create_insight_alert(self.team, name="Signups dropped", detector_config={"type": "zscore"})
        AlertConfiguration.objects.filter(id=row.id).update(created_at=self._at(60))
        names = {str(self.copy_id): "native", str(row.id): "row"}

        response = self.client.get(f"{self.url}/?{query.format(row_insight=row.insight_id)}")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [names[alert["id"]] for alert in response.json()["results"]] == expected

    def test_an_alert_insight_keeps_no_row_for_shows_the_subscribers_its_destinations_name(self) -> None:
        with team_scope(self.team.id):
            platform_testing.forget_source_row(self.copy_id)
            set_subscriber_destinations(
                team_id=self.team.id,
                public_id=self.copy_id,
                user_ids=[self.user.id],
                event_kinds=SUBSCRIBER_EVENT_KINDS,
                in_app_resource_type="insight",
                in_app_resource_id=self.alert.insight.short_id,
            )
            view = get_configuration(
                team_id=self.team.id, source_kinds=[SourceKind.INSIGHT.value], configuration_id=self.copy_id
            )
        AlertConfiguration.objects.filter(id=self.alert.id).delete()

        listed = self.client.get(f"{self.url}/").json()["results"]
        detail = self.client.get(f"{self.url}/{self.copy_id}/").json()

        assert [[user["id"] for user in alert["subscribed_users"]] for alert in listed] == [[self.user.id]]
        assert [user["id"] for user in detail["subscribed_users"]] == [self.user.id]
        assert view is not None
        assert first_subscriber_id(team_id=self.team.id, alert_id=self.copy_id) == self.user.id

    def test_a_page_of_alerts_insight_keeps_no_row_for_builds_in_queries_that_do_not_grow_with_it(self) -> None:
        def native(insight_id: int) -> PlatformAlertConfigurationView:
            with team_scope(self.team.id):
                created = platform_testing.create_configuration(
                    team_id=self.team.id,
                    name="native",
                    source_kind="insight",
                    source_config={"insight_id": insight_id},
                    check_interval_minutes=1440,
                    owner="platform",
                    legacy_configuration_id=None,
                    created_by_id=self.user.id,
                )
                view = get_configuration(
                    team_id=self.team.id, source_kinds=[SourceKind.INSIGHT.value], configuration_id=created.id
                )
            assert view is not None
            return view

        views = [native(create_insight_alert(self.team).insight_id) for _ in range(3)]

        def built_queries(page: list[PlatformAlertConfigurationView]) -> int:
            with CaptureQueriesContext(connection) as queries:
                built = AlertConfiguration.from_platform_views(page, team_id=self.team.id)
                for alert in built.values():
                    assert list(alert.subscribed_users.all()) == []
                    assert (alert.insight.name, alert.created_by, hasattr(alert.insight, "prefetched_tags")) == (
                        "insight",
                        self.user,
                        True,
                    )
            assert len(built) == len(page)
            return len(queries)

        # The first build also loads the tag content type, which Django then caches.
        built_queries(views[:1])
        assert built_queries(views[:1]) == built_queries(views)

    def test_the_list_hides_an_alert_insight_keeps_no_row_for_without_insight_access(self) -> None:
        with team_scope(self.team.id):
            platform_testing.forget_source_row(self.copy_id)
        AlertConfiguration.objects.filter(id=self.alert.id).delete()

        with patch(
            "products.access_control.backend.facade.user_access_control.UserAccessControl.filter_queryset_by_access_level",
            side_effect=lambda queryset, *args, **kwargs: queryset.none(),
        ):
            response = self.client.get(f"{self.url}/")

        assert response.json()["results"] == []

    @parameterized.expand([("list",), ("retrieve",)])
    def test_a_moved_alert_reads_back_its_settings_from_the_platform_after_its_row_drifts(self, action: str) -> None:
        threshold = {"type": "absolute", "bounds": {"lower": 10.0, "upper": 50.0}}
        written: dict[str, Any] = {
            "name": "Written",
            "enabled": True,
            "condition": {"type": "absolute_value"},
            "config": {"type": "TrendsAlertConfig", "series_index": 0, "check_ongoing_interval": True},
            "calculation_interval": AlertCalculationInterval.HOURLY.value,
            "skip_weekend": True,
            "schedule_restriction": {"blocked_windows": [{"start": "22:00", "end": "07:00"}]},
            "snoozed_until": _iso(self.now + timedelta(days=1)),
        }
        patched = self.client.patch(
            f"{self.url}/{self.alert.id}/", {**written, "threshold": {"configuration": threshold}}, format="json"
        )
        assert patched.status_code == status.HTTP_200_OK, patched.json()
        # Writes that bypass the API leave the row apart from the copy.
        AlertConfiguration.objects.filter(id=self.alert.id).update(
            name="Drifted",
            enabled=False,
            condition={"type": "relative_increase"},
            config={"type": "TrendsAlertConfig", "series_index": 1},
            calculation_interval=AlertCalculationInterval.DAILY.value,
            skip_weekend=False,
            schedule_restriction=None,
            snoozed_until=None,
        )
        Threshold.objects.filter(alertconfiguration__id=self.alert.id).update(
            configuration={"type": "percentage", "bounds": {"upper": 0.5}}
        )

        row = self._row(action)

        assert {key: row[key] for key in written} == written
        assert (row["threshold"]["configuration"], row["state"]) == (threshold, "Snoozed")

    def test_a_moved_alert_keeps_its_rows_settings_that_an_older_copy_lacks(self) -> None:
        row_config = {"type": "TrendsAlertConfig", "series_index": 0, "check_ongoing_interval": True}
        AlertConfiguration.objects.filter(id=self.alert.id).update(config=row_config, skip_weekend=True)
        with team_scope(self.team.id):
            platform_testing.set_source_config(
                self.copy_id,
                {
                    "insight_id": self.alert.insight_id,
                    SOURCE_CONDITION_KEY: {
                        "comparison": {"type": "absolute_value"},
                        "threshold": {"type": "absolute", "bounds": {"upper": 100.0}},
                    },
                },
            )

        row = self._row("retrieve")

        assert (row["config"], row["skip_weekend"]) == (row_config, True)

    def test_a_platform_history_failure_falls_back_to_the_alerts_own_checks(self) -> None:
        self._record(30, "firing", value=150.0)

        with patch(
            "products.alerts.backend.platform_alert_reads.check_page_by_public_id",
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

    def test_each_subscriber_writer_keeps_the_copys_subscriber_destinations_in_step(self) -> None:
        other = User.objects.create_and_join(self.organization, "other@example.com", None)
        handed_over = create_insight_alert(self.team, next_check_at=self.now + timedelta(minutes=3))
        handed_over.subscribed_users.add(other)

        def copied(alert_id: Any) -> Any:
            with team_scope(self.team.id):
                return subscriber_user_ids_by_public_id(team_id=self.team.id, public_ids=[alert_id])

        cut_over_team(self.team.id, now=self.now)
        assert copied(handed_over.id) == {handed_over.id: (other.id,)}

        edit = self.client.patch(
            f"{self.url}/{self.alert.id}/", {"subscribed_users": [self.user.id, other.id]}, format="json"
        )
        assert edit.status_code == status.HTTP_200_OK, edit.json()
        assert copied(self.alert.id) == {self.alert.id: tuple(sorted([self.user.id, other.id]))}

        with team_scope(self.team.id):
            native = platform_testing.create_configuration(
                team_id=self.team.id,
                name="native",
                source_kind="insight",
                source_config={"insight_id": self.alert.insight_id},
                check_interval_minutes=1440,
                owner="platform",
                legacy_configuration_id=None,
            )
            set_subscriber_destinations(
                team_id=self.team.id,
                public_id=native.id,
                user_ids=[self.user.id, other.id],
                event_kinds=SUBSCRIBER_EVENT_KINDS,
                in_app_resource_type="insight",
                in_app_resource_id=self.alert.insight.short_id,
            )

        with self.captureOnCommitCallbacks(execute=True):
            OrganizationMembership.objects.get(user=other, organization=self.organization).delete()
        assert copied(self.alert.id) == {self.alert.id: (self.user.id,)}
        assert copied(handed_over.id) == {}
        assert copied(native.id) == {native.id: (self.user.id,)}
        # A cleanup that runs after the user joined again, such as a retry, follows the subscriptions
        # where the alert has them, and leaves an alert with no insight row alone.
        with team_scope(self.team.id):
            for public_id in (self.alert.id, native.id):
                set_subscriber_destinations(
                    team_id=self.team.id,
                    public_id=public_id,
                    user_ids=[self.user.id, other.id],
                    event_kinds=SUBSCRIBER_EVENT_KINDS,
                    in_app_resource_type="insight",
                    in_app_resource_id=self.alert.insight.short_id,
                )
        self.organization.memberships.create(user=other)
        remove_departed_subscriber(
            organization_id=str(self.organization.id), user_id=other.id, alert_ids=[str(self.alert.id)]
        )
        assert copied(self.alert.id) == {self.alert.id: (self.user.id,)}
        assert copied(native.id) == {native.id: tuple(sorted([self.user.id, other.id]))}

        cleared = self.client.patch(f"{self.url}/{self.alert.id}/", {"subscribed_users": []}, format="json")
        assert cleared.status_code == status.HTTP_200_OK, cleared.json()
        assert copied(self.alert.id) == {}

    def test_each_api_writes_both_rows_of_an_alert_the_platform_owns(self) -> None:
        stored_config = self._copy().source_config
        # A platform edit names only the settings it sends, so the insight check settings stay as stored.
        self._edit_on_the_platform(
            lambda stored: replace(
                stored,
                name="Edited on the platform",
                source_config={key: stored_config[key] for key in ("insight_id", "condition")},
            )
        )
        assert self._copy().source_config["config"] == stored_config["config"] is not None
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
            ("rename", {"name": "Renamed"}, "firing"),
            (
                "threshold",
                {"threshold": {"configuration": {"type": "absolute", "bounds": {"upper": 200}}}},
                "not_firing",
            ),
        ]
    )
    def test_an_insight_edit_to_a_copy_without_the_check_settings_ends_a_firing_only_on_a_real_change(
        self, _name: str, payload: dict[str, Any], state: str
    ) -> None:
        with team_scope(self.team.id):
            stored_config = self._copy().source_config
            older = {key: stored_config[key] for key in ("insight_id", "condition")}
            platform_testing.set_source_config(self.copy_id, older)
            platform_testing.start_firing(self.copy_id, team_id=self.team.id, at=self.now)

        response = self.client.patch(f"{self.url}/{self.alert.id}/", payload, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        with team_scope(self.team.id):
            instance = platform_testing.alert_for(self.copy_id)
        assert instance is not None
        assert instance.state == state

    @parameterized.expand(
        [
            (f"{name}_{kind}", condition_change, settings_change, kind == "native")
            for name, condition_change, settings_change in [
                ("percentage_bound", {"threshold": {"type": "percentage", "bounds": {"upper": 0.5}}}, {}),
                # The insight API checks a detector against its insight and its access rules, so only it may set one.
                ("detector", {"detector": {"type": "zscore"}}, {}),
                ("series", {}, {"config": {"type": "TrendsAlertConfig", "series_index": 1}}),
                ("skip_weekend", {}, {"skip_weekend": True}),
                ("evaluation_delay", {}, {"evaluation_delay_intervals": 3}),
                ("investigation_agent", {}, {"investigation_agent_enabled": True}),
            ]
            # An alert with no insight row has no row to mirror onto, so the same refusals come from its guard.
            for kind in ("row", "native")
        ]
    )
    def test_a_platform_edit_the_insight_stack_cannot_check_is_refused_on_both_rows(
        self, _name: str, condition_change: dict[str, Any], settings_change: dict[str, Any], native: bool
    ) -> None:
        if native:
            self._forget_the_insight_row()
        stored_config = self._copy().source_config

        def edit(stored: PlatformAlertConfigurationEdit) -> PlatformAlertConfigurationEdit:
            condition = {**stored.source_config["condition"], **condition_change}
            return replace(stored, source_config={**stored.source_config, **settings_change, "condition": condition})

        with pytest.raises(InvalidPlatformAlertEdit):
            self._edit_on_the_platform(edit)

        if not native:
            self.alert.refresh_from_db()
            assert self.alert.threshold is not None
            assert (self.alert.threshold.configuration["type"], self.alert.detector_config) == ("absolute", None)
        assert self._copy().source_config == stored_config

    @parameterized.expand(
        [
            ("rename", {"name": "Renamed"}, status.HTTP_200_OK, lambda copy: copy.name, "Renamed"),
            (
                "threshold",
                {"threshold": {"configuration": {"type": "absolute", "bounds": {"upper": 200}}}},
                status.HTTP_200_OK,
                lambda copy: copy.source_config["condition"]["threshold"]["bounds"],
                {"upper": 200},
            ),
            (
                "cadence",
                {"calculation_interval": AlertCalculationInterval.HOURLY.value},
                status.HTTP_200_OK,
                lambda copy: copy.check_interval_minutes,
                60,
            ),
            ("snooze", {"snoozed_until": "1d"}, status.HTTP_200_OK, lambda copy: copy.snooze_until is not None, True),
            (
                "snooze_with_a_threshold",
                {"snoozed_until": "1d", "threshold": {"configuration": {"type": "absolute", "bounds": {"upper": 200}}}},
                status.HTTP_200_OK,
                lambda copy: copy.next_check_at >= copy.snooze_until,
                True,
            ),
            (
                "investigation_without_a_detector",
                {"investigation_agent_enabled": True},
                status.HTTP_400_BAD_REQUEST,
                lambda copy: copy.source_config["investigation_agent_enabled"],
                False,
            ),
            (
                "gating_without_the_agent",
                {"investigation_gates_notifications": True},
                status.HTTP_400_BAD_REQUEST,
                lambda copy: copy.source_config["investigation_gates_notifications"],
                False,
            ),
        ]
    )
    def test_the_insight_api_edits_an_alert_insight_keeps_no_row_for_with_its_checks(
        self,
        _name: str,
        payload: dict[str, Any],
        expected_status: int,
        read: Callable[[PlatformAlertConfigurationView], Any],
        expected: Any,
    ) -> None:
        self._forget_the_insight_row()
        self._edit_on_the_platform(lambda stored: replace(stored, name="native"))

        response = self.client.patch(f"{self.url}/{self.copy_id}/", payload, format="json")

        assert response.status_code == expected_status, response.json()
        assert read(self._copy()) == expected
        assert not AlertConfiguration.objects.filter(team=self.team).exists()

    def test_subscribers_of_an_alert_insight_keeps_no_row_for_are_its_destinations(self) -> None:
        self._forget_the_insight_row()
        other_insight = Insight.objects.create(
            team=self.team, name="Signups", short_id="signups", query=self.alert.insight.query
        )
        with team_scope(self.team.id):
            assign_native_creator(
                team_id=self.team.id,
                source_kinds=[SourceKind.INSIGHT.value],
                configuration_id=self.copy_id,
                created_by_id=User.objects.create_and_join(self.organization, "creator@example.com", None).id,
            )

        subscribed = self.client.patch(
            f"{self.url}/{self.copy_id}/", {"subscribed_users": [self.user.id]}, format="json"
        )
        moved = self.client.patch(f"{self.url}/{self.copy_id}/", {"insight": other_insight.id}, format="json")

        assert subscribed.status_code == status.HTTP_200_OK, subscribed.json()
        assert [user["id"] for user in subscribed.json()["subscribed_users"]] == [self.user.id]
        assert moved.status_code == status.HTTP_200_OK, moved.json()
        assert [user["id"] for user in moved.json()["subscribed_users"]] == [self.user.id]
        with team_scope(self.team.id):
            in_app = [
                destination.data
                for destination in list_alert_destinations(team_id=self.team.id, configuration_id=self.copy_id)
                if destination.data["type"] == DestinationType.IN_APP
            ]
        assert [(data["in_app_user_ids"], data["in_app_resource_id"]) for data in in_app] == [
            ([self.user.id], "signups")
        ]
        assert insight_short_ids_watched_by(team_id=self.team.id, user_id=self.user.id, limit=10) == ["signups"]
        denied = User.objects.create_and_join(self.organization, "denied@example.com", None)
        self.client.patch(f"{self.url}/{self.copy_id}/", {"subscribed_users": [self.user.id, denied.id]}, format="json")

        def can_view(access_control: UserAccessControl, *_args: object) -> bool:
            return access_control._user.id != denied.id

        with (
            patch.object(UserAccessControl, "check_access_level_for_object", autospec=True, side_effect=can_view),
            patch(
                "products.alerts.backend.presentation.views.alert.send_test_alert_email", return_value=True
            ) as mock_send,
        ):
            tested = self.client.post(f"{self.url}/{self.copy_id}/test-delivery/")
        assert (tested.status_code, tested.json()["email_recipient_count"]) == (status.HTTP_202_ACCEPTED, 1)
        assert mock_send.call_args.kwargs["recipients"] == [self.user.email]

    def test_enabling_an_alert_insight_keeps_no_row_for_keeps_its_requested_start_time(self) -> None:
        self._forget_the_insight_row()
        with team_scope(self.team.id):
            platform_testing.set_enabled(self.copy_id, False)
            assign_native_creator(
                team_id=self.team.id,
                source_kinds=[SourceKind.INSIGHT.value],
                configuration_id=self.copy_id,
                created_by_id=self.user.id,
            )
        start = timezone.now() + timedelta(hours=3)

        response = self.client.patch(
            f"{self.url}/{self.copy_id}/",
            {"enabled": True, "schedule_start_time": start.strftime("%H:%M")},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        next_check_at = self._copy().next_check_at
        assert next_check_at is not None and next_check_at > timezone.now() + timedelta(hours=2)

    def test_renaming_a_firing_alert_insight_keeps_no_row_for_answers_with_its_state(self) -> None:
        with team_scope(self.team.id):
            platform_testing.start_firing(self.copy_id, team_id=self.team.id, at=timezone.now())
        self._forget_the_insight_row()

        response = self.client.patch(f"{self.url}/{self.copy_id}/", {"name": "Renamed"}, format="json")

        assert (response.status_code, response.json()["state"]) == (status.HTTP_200_OK, "Firing"), response.json()

    def test_renaming_a_detector_alert_insight_keeps_no_row_for_keeps_it_without_a_threshold(self) -> None:
        insight = self.alert.insight
        insight.query = {**(insight.query or {}), "trendsFilter": {"display": "ActionsLineGraph"}}
        insight.save(update_fields=["query"])
        self._forget_the_insight_row()
        with team_scope(self.team.id):
            stored_config = self._copy().source_config
            platform_testing.set_source_config(
                self.copy_id,
                {
                    **stored_config,
                    "condition": {**stored_config["condition"], "threshold": None, "detector": {"type": "zscore"}},
                },
            )

        response = self.client.patch(f"{self.url}/{self.copy_id}/", {"name": "Renamed"}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        copy = self._copy()
        assert (copy.name, copy.source_config["condition"]["threshold"]) == ("Renamed", None)

    @parameterized.expand([("counted", False, 1), ("left_out_of_its_own_edit", True, 0)])
    def test_the_ai_detector_cap_counts_an_ai_alert_insight_keeps_no_row_for(
        self, _name: str, editing_it: bool, expected: int
    ) -> None:
        self._forget_the_insight_row()
        with team_scope(self.team.id):
            stored_config = self._copy().source_config
            platform_testing.set_source_config(
                self.copy_id,
                {**stored_config, "condition": {**stored_config["condition"], "detector": {"type": "llm"}}},
            )

        count = count_enabled_llm_alerts(
            team_id=self.team.id, exclude_alert_id=str(self.copy_id) if editing_it else None
        )

        assert count == expected

    @parameterized.expand(
        [
            ("does_not_count_it_against_itself", True, {}),
            ("is_admitted_at_the_cadence_it_moves_to", False, {"calculation_interval": "hourly"}),
        ]
    )
    def test_turning_on_a_real_time_alert_insight_keeps_no_row_for(
        self, _name: str, on_the_plan: bool, payload: dict[str, Any]
    ) -> None:
        self.organization.available_product_features = (
            [{"key": AvailableFeature.REAL_TIME_ALERTS, "name": "Real-time alerts", "limit": 1}] if on_the_plan else []
        )
        self.organization.save()
        self._forget_the_insight_row()
        with team_scope(self.team.id):
            platform_testing.set_check_interval_minutes(self.copy_id, REAL_TIME_CADENCE_MINUTES)
            platform_testing.set_enabled(self.copy_id, False)
            assign_native_creator(
                team_id=self.team.id,
                source_kinds=[SourceKind.INSIGHT.value],
                configuration_id=self.copy_id,
                created_by_id=self.user.id,
            )

        response = self.client.patch(f"{self.url}/{self.copy_id}/", {"enabled": True, **payload}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self._copy().enabled is True

    @parameterized.expand(
        [
            ("ai_alert", {"detector_config": {"type": "llm"}}, True, None),
            ("real_time_alert_over_the_limit", {"calculation_interval": "real_time"}, True, "Limit reached."),
            ("real_time_alert_without_the_plan", {"calculation_interval": "real_time"}, False, None),
        ]
    )
    def test_a_platform_edit_cannot_turn_an_alert_back_on_past_its_admission(
        self, _name: str, stored: dict[str, Any], has_real_time_plan: bool, real_time_limit_error: str | None
    ) -> None:
        self.organization.available_product_features = (
            [{"key": AvailableFeature.REAL_TIME_ALERTS, "name": "Real-time alerts"}] if has_real_time_plan else []
        )
        self.organization.save()
        self._edit_on_the_platform(lambda stored: replace(stored, enabled=False))
        AlertConfiguration.objects.filter(id=self.alert.id).update(**stored)
        if stored.get("calculation_interval") == AlertCalculationInterval.REAL_TIME:
            with team_scope(self.team.id):
                platform_testing.set_check_interval_minutes(self.copy_id, REAL_TIME_CADENCE_MINUTES)

        with (
            patch.object(AlertConfiguration, "check_real_time_alert_limit", return_value=real_time_limit_error),
            pytest.raises(InvalidPlatformAlertEdit) as refused,
        ):
            self._edit_on_the_platform(lambda stored: replace(stored, enabled=True))

        assert refused.value.field_name == "enabled"
        self.alert.refresh_from_db()
        assert (self.alert.enabled, self._copy().enabled) == (False, False)

    @parameterized.expand([("row", False, False), ("row_the_copy_lags", False, True), ("native", True, False)])
    def test_a_snooze_from_slack_mutes_the_platform_copy(self, _name: str, native: bool, copy_lags: bool) -> None:
        if native:
            self._forget_the_insight_row()
        if copy_lags:
            AlertConfiguration.objects.filter(id=self.alert.id).update(name="Renamed")

        # The snooze menu of an alert with no insight row carries its platform alert's id.
        outcome = snooze_alert_from_slack(self.copy_id if native else self.alert.id, user=self.user, duration="1d")

        assert outcome == "snoozed"
        assert self._copy().snooze_until is not None
        if not native:
            self.alert.refresh_from_db()
            assert self._copy().snooze_until == self.alert.snoozed_until

    @parameterized.expand([("copy_off", True, False), ("row_off", False, True)])
    def test_a_snooze_from_slack_refuses_a_moved_alert_unless_row_and_copy_are_on(
        self, _name: str, row_on: bool, copy_on: bool
    ) -> None:
        AlertConfiguration.objects.filter(id=self.alert.id).update(enabled=row_on)
        with team_scope(self.team.id):
            platform_testing.set_enabled(self.copy_id, copy_on)

        outcome = snooze_alert_from_slack(self.alert.id, user=self.user, duration="1d")

        assert outcome == "disabled"
        self.alert.refresh_from_db()
        copy = self._copy()
        assert (self.alert.snoozed_until, copy.enabled, copy.snooze_until) == (None, copy_on, None)

    def test_a_snooze_the_platform_refuses_leaves_both_rows_unsnoozed(self) -> None:
        with patch(
            "products.alerts.backend.platform_ownership.on_updated",
            side_effect=PlatformCannotOwn("The alerts platform cannot run this alert."),
        ):
            outcome = snooze_alert_from_slack(self.alert.id, user=self.user, duration="1d")

        assert outcome == "not_snoozable"
        self.alert.refresh_from_db()
        assert (self.alert.snoozed_until, self._copy().snooze_until) == (None, None)

    @parameterized.expand(
        [
            ("to_real_time", {"calculation_interval": AlertCalculationInterval.REAL_TIME.value}, True),
            ("threshold", {"threshold": {"configuration": {"type": "absolute", "bounds": {"upper": 50}}}}, True),
            ("name_only", {"name": "Renamed"}, False),
        ]
    )
    def test_an_edit_reschedules_the_copy_when_it_reschedules_the_insight_alert(
        self, _name: str, edit: dict[str, Any], rescheduled: bool
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.REAL_TIME_ALERTS, "name": "Real-time alerts"}
        ]
        self.organization.save()
        with team_scope(self.team.id):
            due_before = platform_testing.copy_of(self.alert.id).next_check_at

        response = self.client.patch(f"{self.url}/{self.alert.id}/", edit, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        self.alert.refresh_from_db()
        with team_scope(self.team.id):
            due_after = platform_testing.copy_of(self.alert.id).next_check_at
        assert self.alert.owner == "platform"
        assert due_before is not None and due_after is not None and self.alert.next_check_at is not None
        if rescheduled:
            assert self.alert.next_check_at + timedelta(minutes=1) <= due_after < due_before
        else:
            assert due_after == due_before

    @parameterized.expand([("a_team_on_the_platform", True), ("a_team_off_the_platform", False)])
    def test_a_new_alert_is_handed_over_only_in_a_team_on_the_platform(self, _name: str, begun: bool) -> None:
        team_cutover_at = self.now - timedelta(days=4)
        AlertConfiguration.objects.filter(id=self.alert.id).update(
            owner="platform" if begun else "source", owner_changed_at=team_cutover_at
        )
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
        if begun:
            # The insight stack shadows the new alert only for what is left of the team's week.
            assert created.owner_changed_at == team_cutover_at

    @parameterized.expand(
        [
            ("hourly", {"calculation_interval": "hourly"}, (60, None, None), None),
            (
                "weekly_from_a_start_time",
                {"calculation_interval": "weekly", "schedule_start_time": "09:30"},
                (60 * 24 * 7, "week", "09:30"),
                None,
            ),
            (
                "snoozed",
                {"calculation_interval": "hourly", "snoozed_until": "2099-01-01T00:00:00Z"},
                (60, None, None),
                datetime(2099, 1, 1, tzinfo=UTC),
            ),
        ]
    )
    def test_a_create_in_a_team_creating_native_alerts_writes_only_the_platform(
        self,
        _name: str,
        schedule: dict[str, str],
        cadence: tuple[int, str | None, str | None],
        snooze_until: datetime | None,
    ) -> None:
        insight = create_insight_alert(self.team).insight
        payload = {
            "insight": insight.id,
            "subscribed_users": [self.user.id],
            "condition": {"type": "absolute_value"},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "name": "A new alert",
            "threshold": {"configuration": {"type": "absolute", "bounds": {"upper": 100}}},
            **schedule,
        }
        row = self.client.post(f"{self.url}", payload, format="json")
        rows_before = AlertConfiguration.objects.filter(team=self.team).count()

        with patch("products.alerts.backend.platform_ownership.posthoganalytics.feature_enabled", return_value=True):
            response = self.client.post(f"{self.url}", payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert AlertConfiguration.objects.filter(team=self.team).count() == rows_before
        created_id = UUID(response.json()["id"])
        with team_scope(self.team.id):
            created = get_configuration(
                team_id=self.team.id, source_kinds=[SourceKind.INSIGHT.value], configuration_id=created_id
            )
        assert created is not None
        assert (created.legacy_configuration_id, created.created_by_id) == (None, self.user.id)
        assert (created.check_interval_minutes, created.recurrence_unit, created.anchor_time) == cadence
        assert created.snooze_until == snooze_until
        assert (response.json()["snoozed_until"] is not None) == (snooze_until is not None)
        assert created.source_config["condition"]["threshold"]["bounds"] == {"upper": 100}
        assert set(response.json()) == set(row.json())
        assert [user["id"] for user in response.json()["subscribed_users"]] == [self.user.id]
        assert subscriber_user_ids_by_public_id(team_id=self.team.id, public_ids=[created_id]) == {
            created_id: (self.user.id,)
        }

    def test_the_insight_api_embeds_alerts_insight_keeps_no_row_for_in_one_read_per_page(self) -> None:
        def create_native_alert(insight: Insight | None = None) -> tuple[int, str]:
            insight = insight or Insight.objects.create(team=self.team, query=self.alert.insight.query)
            with patch(
                "products.alerts.backend.platform_ownership.posthoganalytics.feature_enabled", return_value=True
            ):
                created = self.client.post(
                    self.url,
                    {
                        "insight": insight.id,
                        "subscribed_users": [self.user.id],
                        "condition": {"type": "absolute_value"},
                        "config": {"type": "TrendsAlertConfig", "series_index": 0},
                        "name": "A new alert",
                        "threshold": {"configuration": {"type": "absolute", "bounds": {"upper": 100}}},
                    },
                    format="json",
                )
            assert created.status_code == status.HTTP_201_CREATED, created.json()
            return insight.id, created.json()["id"]

        self.organization.available_product_features = [{"key": AvailableFeature.ALERTS, "name": "Alerts"}]
        self.organization.save()
        insights_url = f"/api/environments/{self.team.id}/insights/"
        insight_id, alert_id = create_native_alert()

        retrieved = self.client.get(f"{insights_url}{insight_id}/")
        with CaptureQueriesContext(connection) as one_native:
            listed = self.client.get(insights_url)
        create_native_alert()
        create_native_alert()
        with CaptureQueriesContext(connection) as three_native:
            self.client.get(insights_url)

        embedded = [
            (alert["id"], alert["threshold"]["configuration"]["bounds"]) for alert in retrieved.json()["alerts"]
        ]
        assert embedded == [(alert_id, {"upper": 100})]
        listed_alerts = {
            insight["id"]: [alert["id"] for alert in insight["alerts"]] for insight in listed.json()["results"]
        }
        assert listed_alerts[insight_id] == [alert_id]
        assert len(three_native.captured_queries) == len(one_native.captured_queries)

        watched = Insight.objects.get(id=insight_id)
        create_native_alert(watched)
        create_native_alert(watched)
        retrieved_three = self.client.get(f"{insights_url}{insight_id}/")
        assert len(retrieved_three.json()["alerts"]) == 3

        sharing = SharingConfiguration.objects.create(team=self.team, insight=watched, enabled=True)
        self.client.logout()
        shared = self.client.get(f"{insights_url}{insight_id}/?sharing_access_token={sharing.access_token}")
        assert shared.status_code == status.HTTP_200_OK, shared.json()
        assert shared.json()["alerts"] == []

    def test_the_insight_api_embeds_a_moved_alert_as_the_platform_holds_it(self) -> None:
        self._edit_on_the_platform(lambda stored: replace(stored, name="Edited on the platform", enabled=False))
        AlertConfiguration.objects.filter(id=self.alert.id).update(name="Drifted", enabled=True)

        retrieved = self.client.get(f"/api/environments/{self.team.id}/insights/{self.alert.insight_id}/")

        assert [(alert["id"], alert["name"], alert["enabled"]) for alert in retrieved.json()["alerts"]] == [
            (str(self.alert.id), "Edited on the platform", False)
        ]

    def test_the_insight_api_embeds_no_native_alert_that_moved_to_another_insight(self) -> None:
        listed_on = Insight.objects.create(team=self.team, query=self.alert.insight.query)
        moved_to = Insight.objects.create(team=self.team, query=self.alert.insight.query)
        with patch("products.alerts.backend.platform_ownership.posthoganalytics.feature_enabled", return_value=True):
            created = self.client.post(
                self.url,
                {
                    "insight": moved_to.id,
                    "subscribed_users": [],
                    "condition": {"type": "absolute_value"},
                    "config": {"type": "TrendsAlertConfig", "series_index": 0},
                    "name": "Moved",
                    "threshold": {"configuration": {"type": "absolute", "bounds": {"upper": 100}}},
                },
                format="json",
            )
        assert created.status_code == status.HTTP_201_CREATED, created.json()

        # The alert moves between the read that lists it under an insight and the read of its settings.
        with patch(
            "products.alerts.backend.facade.platform.native_insight_alert_ids_by_insight",
            return_value={listed_on.id: [UUID(created.json()["id"])]},
        ):
            retrieved = self.client.get(f"/api/environments/{self.team.id}/insights/{listed_on.id}/")

        assert retrieved.status_code == status.HTTP_200_OK, retrieved.json()
        assert retrieved.json()["alerts"] == []

    def test_a_native_alerts_activity_names_its_insight_after_it_is_deleted(self) -> None:
        insight = Insight.objects.create(team=self.team, name="Signups", query=self.alert.insight.query)
        with patch("products.alerts.backend.platform_ownership.posthoganalytics.feature_enabled", return_value=True):
            created = self.client.post(
                self.url,
                {
                    "insight": insight.id,
                    "subscribed_users": [],
                    "condition": {"type": "absolute_value"},
                    "config": {"type": "TrendsAlertConfig", "series_index": 0},
                    "name": "A new alert",
                    "threshold": {"configuration": {"type": "absolute", "bounds": {"upper": 100}}},
                },
                format="json",
            )
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        deleted = self.client.delete(f"{self.url}/{created.json()['id']}/")

        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        logged = ActivityLog.objects.filter(
            team_id=self.team.id, scope="PlatformAlertConfiguration", item_id=created.json()["id"]
        )
        assert sorted((row.activity, (row.detail or {}).get("context")) for row in logged) == [
            (
                activity,
                {
                    "source_kind": "insight",
                    "alert_id": created.json()["id"],
                    "source_id": insight.short_id,
                    "source_name": "Signups",
                },
            )
            for activity in ("created", "deleted")
        ]

    def _forget_the_insight_row(self) -> None:
        with team_scope(self.team.id):
            platform_testing.forget_source_row(self.copy_id)
        AlertConfiguration.objects.filter(id=self.alert.id).delete()

    @parameterized.expand(
        [
            ("statistical_alert", None, True, None, status.HTTP_200_OK),
            # Its checks would run as the requester, who is not on the AI detector's rollout.
            ("ai_alert_without_the_rollout", {"type": "llm"}, False, None, status.HTTP_400_BAD_REQUEST),
            ("series_gone_from_the_insight", None, True, 5, status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_taking_ownership_of_an_alert_insight_keeps_no_row_for_writes_the_platform(
        self, _name: str, detector: dict[str, Any] | None, rolled_out: bool, series_index: int | None, expected: int
    ) -> None:
        former_member = User.objects.create_user(email="former-member@example.com", first_name="", password=None)
        with team_scope(self.team.id):
            stored_config = self._copy().source_config
            config = (
                stored_config["config"]
                if series_index is None
                else {**stored_config["config"], "series_index": series_index}
            )
            platform_testing.set_source_config(
                self.copy_id,
                {**stored_config, "config": config, "condition": {**stored_config["condition"], "detector": detector}},
            )
            platform_testing.set_enabled(self.copy_id, False)
        self._forget_the_insight_row()
        with team_scope(self.team.id):
            assign_native_creator(
                team_id=self.team.id,
                source_kinds=[SourceKind.INSIGHT.value],
                configuration_id=self.copy_id,
                created_by_id=former_member.id,
            )

        with patch(
            "products.alerts.backend.llm_detector_limits.posthoganalytics.feature_enabled", return_value=rolled_out
        ):
            response = self.client.post(f"{self.url}/{self.copy_id}/take_ownership/")

        assert response.status_code == expected, response.json()
        copy = self._copy()
        taken = expected == status.HTTP_200_OK
        assert (copy.created_by_id, copy.enabled) == ((self.user.id, True) if taken else (former_member.id, False))
        if taken:
            assert (response.json()["created_by"]["id"], response.json()["enabled"]) == (self.user.id, True)
            assert ActivityLog.objects.filter(
                scope="AlertConfiguration", item_id=str(self.copy_id), activity="took_ownership", user=self.user
            ).exists()

    @parameterized.expand(
        [
            (f"{name}_{kind}", reader, enabled, expected, kind == "native")
            for name, reader, enabled, expected in [
                ("team", "team_of", True, True),
                # A snooze from Slack resolves the team first, and a switched-off alert answers it with "disabled".
                ("team_of_a_switched_off_alert", "team_of", False, True),
                ("enabled_insights", "enabled_alert_insights", True, True),
                ("enabled_insights_skip_a_switched_off_alert", "enabled_alert_insights", False, False),
                ("enabled_given_insights", "enabled_alerts_of_given_insights", True, True),
                ("enabled_list", "enabled_alerts_list", True, True),
                ("enabled_list_skips_a_switched_off_alert", "enabled_alerts_list", False, False),
                ("watched_insights", "insights_the_creator_watches", True, True),
                # The cleanup of generated insights keeps an insight any alert points at, on or off.
                ("insights_with_alerts", "insights_with_alerts", True, True),
                ("insights_with_alerts_include_a_switched_off_alert", "insights_with_alerts", False, True),
            ]
            for kind in ("native", "copy")
        ]
    )
    def test_the_facade_readers_read_an_alert_the_platform_owns_from_the_platform(
        self, _name: str, reader: str, enabled: bool, expected: bool, native: bool
    ) -> None:
        if native:
            self._forget_the_insight_row()
        else:
            # A row that drifted from its copy, which the readers must not follow.
            AlertConfiguration.objects.filter(id=self.alert.id).update(enabled=not enabled, created_by=self.user)
        public_id = self.copy_id if native else self.alert.id
        with team_scope(self.team.id):
            platform_testing.set_enabled(self.copy_id, enabled)
            platform_testing.set_created_by(self.copy_id, self.user.id)
        insight = self.alert.insight
        reads: dict[str, Callable[[], bool]] = {
            "team_of": lambda: get_alert_team_id(public_id) == self.team.id,
            "enabled_alert_insights": lambda: insight.id in enabled_alert_insight_ids(team_ids=[self.team.id]),
            "enabled_alerts_of_given_insights": lambda: (
                insight_ids_with_enabled_alerts(team_id=self.team.id, insight_ids=[insight.id]) == {insight.id}
            ),
            "enabled_alerts_list": lambda: (
                [alert.id for alert in list_enabled_alerts(self.team, self.user, limit=10)] == [public_id]
            ),
            "insights_the_creator_watches": lambda: (
                insight_short_ids_watched_by(team_id=self.team.id, user_id=self.user.id, limit=10) == [insight.short_id]
            ),
            "insights_with_alerts": lambda: insight_ids_with_alerts([insight.id]) == {insight.id},
        }

        assert reads[reader]() is expected

    @parameterized.expand([("copy_on", True), ("copy_off", False)])
    def test_a_subscriber_watches_a_moved_alert_behind_newer_alerts(self, _name: str, copy_on: bool) -> None:
        subscriber = User.objects.create_and_join(self.organization, "subscriber@example.com", None)
        AlertSubscription.objects.create(alert_configuration=self.alert, user=subscriber, created_by=self.user)
        with team_scope(self.team.id):
            platform_testing.set_enabled(self.copy_id, copy_on)
            for _ in range(WATCHED_ROWS_PER_INSIGHT):
                newer = Insight.objects.create(team=self.team, query=self.alert.insight.query)
                platform_testing.create_configuration(
                    team_id=self.team.id,
                    name="newer",
                    source_kind=SourceKind.INSIGHT,
                    source_config={"insight_id": newer.id},
                    check_interval_minutes=60 * 24,
                    recurrence_unit="day",
                    owner=PlatformAlertOwner.PLATFORM,
                    destinations_owner=PlatformAlertOwner.PLATFORM,
                )

        watched = insight_short_ids_watched_by(team_id=self.team.id, user_id=subscriber.id, limit=1)

        assert watched == ([self.alert.insight.short_id] if copy_on else [])

    @parameterized.expand(
        [
            (f"{situation}_{kind}", situation, listed, kind == "native")
            for situation, listed in [
                ("firing", True),
                ("not_firing", False),
                ("snoozed", False),
                ("errored_check", False),
                ("switched_off", False),
            ]
            for kind in ("native", "copy")
        ]
    )
    def test_todays_firing_alerts_list_an_alert_the_platform_owns_while_it_fires(
        self, _name: str, situation: str, listed: bool, native: bool
    ) -> None:
        if native:
            self._forget_the_insight_row()
        else:
            AlertConfiguration.objects.filter(id=self.alert.id).update(
                state=AlertState.NOT_FIRING if listed else AlertState.FIRING, created_by=self.user
            )
        public_id = self.copy_id if native else self.alert.id
        with team_scope(self.team.id):
            platform_testing.set_created_by(self.copy_id, self.user.id)
            if situation != "not_firing":
                platform_testing.start_firing(self.copy_id, team_id=self.team.id, at=self.now)
            if situation == "errored_check":
                platform_testing.set_check_status(self.copy_id, "errored")
            if situation == "switched_off":
                platform_testing.set_enabled(self.copy_id, False)
        if situation == "snoozed":
            snoozed = self.client.patch(
                f"{self.url}/{public_id}/", {"snoozed_until": (self.now + timedelta(hours=1)).isoformat()}
            )
            assert snoozed.status_code == status.HTTP_200_OK, snoozed.json()

        firing = list_firing_alerts_created_by(self.team, self.user, include_metrics_insights=True, limit=10)
        errored = list_errored_alerts(self.team, UserAccessControl(self.user, team=self.team), limit=10)

        assert [alert.id for alert in firing] == ([public_id] if listed else [])
        assert [alert.id for alert in errored] == ([public_id] if situation == "errored_check" else [])

    def test_taking_ownership_of_an_ai_alert_insight_keeps_no_row_for_reads_it_under_the_lock(self) -> None:
        insight = self.alert.insight
        insight.query = {**(insight.query or {}), "trendsFilter": {"display": "ActionsLineGraph"}}
        insight.save(update_fields=["query"])
        create_insight_alert(self.team, detector_config={"type": "llm"}, enabled=True)
        with team_scope(self.team.id):
            stored_config = self._copy().source_config
            platform_testing.set_source_config(
                self.copy_id,
                {**stored_config, "condition": {**stored_config["condition"], "detector": {"type": "llm"}}},
            )
        self._forget_the_insight_row()
        with team_scope(self.team.id):
            view = native_insight_alert_view(self.team.id, self.copy_id)
            assert view is not None
            seen_enabled = AlertConfiguration.from_platform_view(view, team_id=self.team.id)
            assert seen_enabled is not None and seen_enabled.enabled
            platform_testing.set_enabled(self.copy_id, False)

        with (
            patch.object(AlertViewSet, "_alert_or_native", return_value=seen_enabled),
            patch("products.alerts.backend.llm_detector_limits.posthoganalytics.feature_enabled", return_value=True),
            patch("products.alerts.backend.llm_detector_limits.max_llm_alerts_per_team", return_value=1),
        ):
            response = self.client.post(f"{self.url}/{self.copy_id}/take_ownership/")

        assert (response.status_code, response.json()["attr"]) == (status.HTTP_400_BAD_REQUEST, "detector_config")
        assert self._copy().enabled is False

    @parameterized.expand([("row", False), ("insight_keeps_no_row_for", True)])
    def test_simulate_reads_a_saved_alert_only_with_the_insight_it_watches(self, _name: str, native: bool) -> None:
        other_insight = create_insight_alert(self.team).insight
        if native:
            self._forget_the_insight_row()
        alert_id = str(self.copy_id if native else self.alert.id)

        with patch(
            "products.alerts.backend.presentation.views.alert.simulate_detector_on_insight",
            side_effect=ValueError("simulated"),
        ):
            elsewhere = self.client.post(
                f"{self.url}/simulate/", {"insight": other_insight.id, "alert": alert_id}, format="json"
            )
            watched = self.client.post(
                f"{self.url}/simulate/", {"insight": self.alert.insight_id, "alert": alert_id}, format="json"
            )

        assert elsewhere.json()["attr"] == "alert", elsewhere.json()
        assert watched.json()["detail"] == "simulated", watched.json()

    @patch("products.alerts.backend.presentation.views.alert.trigger_alert_hog_functions")
    def test_destinations_of_an_alert_insight_keeps_no_row_for_match_its_platform_id(self, mock_trigger) -> None:
        mock_trigger.return_value = [
            AlertDelivery(channel="hog_function", target="Eng alerts", template="slack", at="2026-08-11T00:00:00+00:00")
        ]
        sync_template_to_db(template_slack)
        integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T123",
            config={"authed_user": {"id": "u"}},
            sensitive_config={"access_token": "xoxb-test"},
        )
        self._forget_the_insight_row()
        alert_url = f"{self.url}/{self.copy_id}"

        created = self.client.post(
            f"{alert_url}/destinations/",
            {
                "type": "slack",
                "slack_workspace_id": integration.id,
                "slack_channel_id": "C123",
                "slack_channel_name": "product-alerts",
            },
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        [hog_function_id] = created.json()["hog_function_ids"]
        assert (HogFunction.objects.get(id=hog_function_id).filters or {})["properties"][0]["value"] == str(
            self.copy_id
        )
        tested = self.client.post(f"{alert_url}/test-delivery/")
        assert (tested.status_code, tested.json()["destination_count"]) == (status.HTTP_202_ACCEPTED, 1)

        deleted = self.client.post(
            f"{alert_url}/destinations/delete/", {"hog_function_ids": [hog_function_id]}, format="json"
        )

        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert self.client.post(f"{alert_url}/test-delivery/").status_code == status.HTTP_409_CONFLICT

    def _destination(self, alert_id: UUID | None = None) -> HogFunction:
        return HogFunction.objects.create(
            team=self.team,
            type="internal_destination",
            name="Slack",
            hog="return event",
            enabled=True,
            filters={
                "events": [{"id": "$insight_alert_firing", "type": "events"}],
                "properties": [
                    {"key": "alert_id", "value": str(alert_id or self.alert.id), "operator": "exact", "type": "event"}
                ],
            },
        )

    @parameterized.expand([("alert_api",), ("insight_delete",), ("alert_api_with_no_insight_row",)])
    def test_deleting_a_moved_alert_deletes_its_copy_and_destinations(self, route: str) -> None:
        native = route == "alert_api_with_no_insight_row"
        if native:
            self._forget_the_insight_row()
        destination = self._destination(self.copy_id if native else None)

        async def run_cleanup_inline(inputs: NativeCleanupInputs) -> None:
            for configuration_id in native_alert_ids(inputs):
                delete_native_alert(inputs.team_id, configuration_id)

        with (
            patch("products.alerts.backend.platform_native_cleanup._start", side_effect=run_cleanup_inline),
            self.captureOnCommitCallbacks(execute=True),
        ):
            if route != "insight_delete":
                response = self.client.delete(f"{self.url}/{self.copy_id if native else self.alert.id}/")
            else:
                response = self.client.patch(
                    f"/api/projects/{self.team.id}/insights/{self.alert.insight_id}", {"deleted": True}
                )

        assert response.status_code in (status.HTTP_204_NO_CONTENT, status.HTTP_200_OK)
        destination.refresh_from_db()
        with team_scope(self.team.id):
            copy = get_configuration(
                team_id=self.team.id, source_kinds=[SourceKind.INSIGHT.value], configuration_id=self.copy_id
            )
        assert (copy, destination.deleted, AlertConfiguration.objects.filter(id=self.alert.id).exists()) == (
            None,
            True,
            False,
        )

    def test_deleting_an_alert_row_directly_leaves_its_copy_and_destinations(self) -> None:
        destination = self._destination()

        with self.captureOnCommitCallbacks(execute=True):
            AlertConfiguration.objects.get(id=self.alert.id).delete()

        destination.refresh_from_db()
        with team_scope(self.team.id):
            copy = get_configuration(
                team_id=self.team.id, source_kinds=[SourceKind.INSIGHT.value], configuration_id=self.copy_id
            )
        assert (copy is not None, destination.deleted) == (True, False)
