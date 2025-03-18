# NOTE: This isn't testing any of the custom Web Analytics code,
# but rather testing the revenue code in insights/trends/aggregation_operations.py
from typing import Any, Optional
from decimal import Decimal

from posthog.hogql_queries.insights.trends.trends_query_builder import TrendsQuery, EventsNode
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.models.utils import uuid7
from posthog.schema import DateRange, IntervalType, PropertyMathType


from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)
from freezegun import freeze_time


@snapshot_clickhouse_queries
class TestWebAnalyticsRevenue(ClickhouseTestMixin, APIBaseTest):
    def _create_events(self, data, event="product_sold"):
        person_result = []
        for id, events in data:
            with freeze_time(events[0][0]):
                person_result.append(
                    _create_person(
                        team_id=self.team.pk,
                        distinct_ids=[id],
                        properties={
                            "name": id,
                            **({"email": "test@posthog.com"} if id == "test" else {}),
                        },
                    )
                )

            for timestamp, session_id, properties in events:
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=id,
                    timestamp=timestamp,
                    properties={"$session_id": session_id, **properties},
                )

        return person_result

    def _create_query_runner(
        self,
        date_from: str,
        date_to: Optional[str],
        interval: IntervalType,
        series: list[EventsNode],
        properties: Optional[Any] = None,
    ) -> TrendsQueryRunner:
        query = TrendsQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            interval=interval,
            series=series,
            properties=properties,
        )

        return TrendsQueryRunner(team=self.team, query=query)

    def test_revenue_currency_property(self):
        self.team.revenue_tracking_config = {"baseCurrency": "USD"}
        self.team.save()

        # Storing as USD here
        self._create_events(
            [
                (
                    "user1",
                    [
                        ("2024-01-01", str(uuid7()), {"revenue": 100, "currency": "USD"}),
                        ("2024-01-02", str(uuid7()), {"revenue": 200, "currency": "USD"}),
                    ],
                ),
                (
                    "user2",
                    [
                        ("2024-01-01", str(uuid7()), {"revenue": 150, "currency": "USD"}),
                        ("2024-01-02", str(uuid7()), {"revenue": 250, "currency": "USD"}),
                    ],
                ),
            ]
        )

        # Using the `currency` field, and because base is USD will keep value constant
        query_runner = self._create_query_runner(
            date_from="2024-01-01",
            date_to="2024-01-02",
            interval=IntervalType.DAY,
            series=[
                EventsNode(
                    event="product_sold",
                    math=PropertyMathType.SUM,
                    math_property="revenue",
                    math_property_revenue_currency={"property": "currency"},
                )
            ],
        )

        results = query_runner.run().results[0]
        assert results["data"] == [Decimal("250"), Decimal("450")]

    def test_revenue_currency_static(self):
        self.team.revenue_tracking_config = {"baseCurrency": "USD"}
        self.team.save()

        # Storing as USD here
        self._create_events(
            [
                (
                    "user1",
                    [
                        ("2024-01-01", str(uuid7()), {"revenue": 100, "currency": "USD"}),
                        ("2024-01-02", str(uuid7()), {"revenue": 200, "currency": "USD"}),
                    ],
                ),
                (
                    "user2",
                    [
                        ("2024-01-01", str(uuid7()), {"revenue": 150, "currency": "USD"}),
                        ("2024-01-02", str(uuid7()), {"revenue": 250, "currency": "USD"}),
                    ],
                ),
            ]
        )

        # But rather than using the `currency` field, we're treating `revenue` as static GBP
        query_runner = self._create_query_runner(
            date_from="2024-01-01",
            date_to="2024-01-02",
            interval=IntervalType.DAY,
            series=[
                EventsNode(
                    event="product_sold",
                    math=PropertyMathType.SUM,
                    math_property="revenue",
                    math_property_revenue_currency={"static": "GBP"},
                )
            ],
        )

        results = query_runner.run().results[0]
        assert results["data"] == [Decimal("318.3902190523"), Decimal("569.764497341")]
