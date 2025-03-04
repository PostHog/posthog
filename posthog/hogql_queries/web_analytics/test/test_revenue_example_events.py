from typing import Optional

from freezegun import freeze_time

from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.web_analytics.revenue_example_events import RevenueExampleEventsQueryRunner
from posthog.models.utils import uuid7
from posthog.schema import (
    RevenueExampleEventsQuery,
    RevenueTrackingConfig,
    RevenueExampleEventsQueryResponse,
    RevenueTrackingEventItem,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
)

EMPTY_REVENUE_TRACKING_CONFIG = RevenueTrackingConfig(events=[])

SINGLE_EVENT_REVENUE_TRACKING_CONFIG = RevenueTrackingConfig(
    events=[RevenueTrackingEventItem(eventName="purchase", revenueProperty="revenue")]
)

MULTIPLE_EVENT_REVENUE_TRACKING_CONFIG = RevenueTrackingConfig(
    events=[
        RevenueTrackingEventItem(eventName="purchase_a", revenueProperty="revenue_a"),
        RevenueTrackingEventItem(eventName="purchase_b", revenueProperty="revenue_b"),
    ]
)


class TestRevenueExampleEventsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-01-29"

    def _create_events(self, data, event="$pageview"):
        person_result = []
        for distinct_id, timestamps in data:
            with freeze_time(timestamps[0][0]):
                person = _create_person(
                    team_id=self.team.pk,
                    distinct_ids=[distinct_id],
                    properties={
                        "name": distinct_id,
                        **({"email": "test@posthog.com"} if distinct_id == "test" else {}),
                    },
                )
            event_ids: list[str] = []
            for timestamp, session_id, *extra in timestamps:
                url = None
                elements = None
                lcp_score = None
                revenue = None
                revenue_property = "revenue"

                if event == "$pageview":
                    url = extra[0] if extra else None
                elif event == "$autocapture":
                    elements = extra[0] if extra else None
                elif event == "$web_vitals":
                    lcp_score = extra[0] if extra else None
                elif event.startswith("purchase"):
                    # purchase_a -> revenue_a, purchase_b -> revenue_b, etc
                    revenue_property += event[8:]
                    revenue = extra[0] if extra else None
                properties = extra[1] if extra and len(extra) > 1 else {}

                event_ids.append(
                    _create_event(
                        team=self.team,
                        event=event,
                        distinct_id=distinct_id,
                        timestamp=timestamp,
                        properties={
                            "$session_id": session_id,
                            "$current_url": url,
                            "$web_vitals_LCP_value": lcp_score,
                            revenue_property: revenue,
                            **properties,
                        },
                        elements=elements,
                    )
                )
            person_result.append((person, event_ids))
        return person_result

    def _run_revenue_example_events_query(
        self,
        revenue_tracking_config: RevenueTrackingConfig,
        limit_context: Optional[LimitContext] = None,
    ):
        with freeze_time(self.QUERY_TIMESTAMP):
            query = RevenueExampleEventsQuery(
                revenueTrackingConfig=revenue_tracking_config,
            )
            runner = RevenueExampleEventsQueryRunner(team=self.team, query=query, limit_context=limit_context)
            response = runner.calculate()
            RevenueExampleEventsQueryResponse.model_validate(response)
            return response

    def test_no_crash_when_no_data(self):
        self._run_revenue_example_events_query(EMPTY_REVENUE_TRACKING_CONFIG)

    def test_single_event(self):
        s11 = str(uuid7("2023-12-02"))

        self._create_events(
            [
                ("p1", [("2023-12-02", s11, 42)]),
            ],
            event="purchase",
        )

        results = self._run_revenue_example_events_query(SINGLE_EVENT_REVENUE_TRACKING_CONFIG).results

        assert len(results) == 1
        assert results[0][1] == "purchase"
        assert results[0][2] == 42

    def test_multiple_events(self):
        s1 = str(uuid7("2023-12-02"))
        self._create_events(
            [
                ("p1", [("2023-12-02", s1, 42)]),
            ],
            event="purchase_a",
        )
        s2 = str(uuid7("2023-12-03"))
        self._create_events(
            [
                ("p2", [("2023-12-03", s2, 43)]),
            ],
            event="purchase_b",
        )

        results = self._run_revenue_example_events_query(MULTIPLE_EVENT_REVENUE_TRACKING_CONFIG).results

        assert len(results) == 2
        assert results[0][1] == "purchase_b"
        assert results[0][2] == 43
        assert results[1][1] == "purchase_a"
        assert results[1][2] == 42
