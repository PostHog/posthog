from datetime import UTC, datetime
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.utils import absolute_uri

from products.alerts.backend.logic.insight_alert_destinations import snooze_select
from products.alerts.backend.platform_alert_wording import describe_insight_transition
from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    AnnouncedTransition,
    MessageDetail,
    MessageLink,
    SourceDescription,
)

DETAIL: dict[str, Any] = {
    "breaches": ["Signups (50) is less than lower threshold (100)"],
    "insight_name": "Signups",
    "insight_short_id": "abc123",
    "insight_chart_asset_id": 7,
    "insight_chart_render_user_id": 3,
    "alert_id": "01900000-0000-0000-0000-000000000001",
}
LINK = MessageLink(label="View insight", url=absolute_uri("/project/7/insights/abc123"))


class TestDescribeInsightTransition(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "a_firing_states_its_breach_and_shows_and_links_its_insight",
                AlertEventKind.FIRING,
                DETAIL,
                SourceDescription(
                    details=(MessageDetail(label="Threshold breached", value=DETAIL["breaches"][0]),),
                    context=("Insight: Signups",),
                    data_link=LINK,
                    slack_elements=(snooze_select("01900000-0000-0000-0000-000000000001"),),
                ),
            ),
            (
                "every_breach_survives_a_transport_that_keys_details_by_label",
                AlertEventKind.FIRING,
                {**DETAIL, "breaches": ["Series A is above 10", "Series B is above 10"]},
                SourceDescription(
                    details=(
                        MessageDetail(label="Threshold breached", value="Series A is above 10\nSeries B is above 10"),
                    ),
                    context=("Insight: Signups",),
                    data_link=LINK,
                    slack_elements=(snooze_select("01900000-0000-0000-0000-000000000001"),),
                ),
            ),
            # The platform states a failure in its own words, so only the insight's name and link are added.
            (
                "an_error_keeps_the_platform_failure_details",
                AlertEventKind.ERRORED,
                DETAIL,
                SourceDescription(context=("Insight: Signups",), data_link=LINK),
            ),
            # A row recorded before checks kept their detail falls back to the platform's wording.
            ("a_row_without_detail_says_nothing_extra", AlertEventKind.FIRING, {}, SourceDescription()),
        ]
    )
    def test_the_insight_words_a_native_message(
        self, _name: str, kind: AlertEventKind, detail: dict[str, Any], expected: SourceDescription
    ) -> None:
        transition = AnnouncedTransition(
            grouping_key="",
            kind=kind,
            episode_started_at=None,
            value=50.0,
            labels={},
            condition={},
            source_config={},
            error_message=None,
            occurred_at=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
            source_detail=detail,
        )

        assert describe_insight_transition(project_id=7, transition=transition) == expected
