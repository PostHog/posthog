from datetime import datetime
from typing import Optional

from posthog.test.base import APIBaseTest

from posthog.schema import DateRange, EventsNode, FunnelConversionWindowTimeUnit, FunnelsFilter, FunnelsQuery

from posthog.constants import FunnelOrderType
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.hogql_queries.insights.funnels.test.test_funnel_persons import get_actors
from posthog.test.test_journeys import journeys_for


def funnel_conversion_time_test_factory(funnel_order_type: FunnelOrderType):
    class TestFunnelConversionTime(APIBaseTest):
        def _get_actor_ids_at_step(
            self,
            query: FunnelsQuery,
            funnel_step: int,
            breakdown_value: Optional[str | float | list[str | float]] = None,
        ) -> list[str]:
            actors = get_actors(
                query,
                self.team,
                funnel_step=funnel_step,
                funnel_step_breakdown=breakdown_value,
            )
            return [actor[0] for actor in actors]

        def test_funnel_with_multiple_incomplete_tries(self):
            query = FunnelsQuery(
                dateRange=DateRange(
                    date_from="2021-05-01 00:00:00",
                    date_to="2021-05-14 00:00:00",
                ),
                funnelsFilter=FunnelsFilter(
                    funnelOrderType=funnel_order_type,
                    funnelWindowInterval=1,
                ),
                series=[
                    EventsNode(
                        event="user signed up",
                        name="user signed up",
                    ),
                    EventsNode(
                        event="$pageview",
                        name="$pageview",
                    ),
                    EventsNode(
                        event="something else",
                        name="something else",
                    ),
                ],
            )

            people = journeys_for(
                {
                    "person1": [
                        # person1 completed funnel on 2021-05-01
                        {
                            "event": "user signed up",
                            "timestamp": datetime(2021, 5, 1, 1),
                        },
                        {"event": "$pageview", "timestamp": datetime(2021, 5, 1, 2)},
                        {
                            "event": "something else",
                            "timestamp": datetime(2021, 5, 1, 3),
                        },
                        # person1 completed part of funnel on 2021-05-03 and took 2 hours to convert
                        {
                            "event": "user signed up",
                            "timestamp": datetime(2021, 5, 3, 4),
                        },
                        {"event": "$pageview", "timestamp": datetime(2021, 5, 3, 5)},
                        # person1 completed part of funnel on 2021-05-04 and took 3 hours to convert
                        {
                            "event": "user signed up",
                            "timestamp": datetime(2021, 5, 4, 7),
                        },
                        {"event": "$pageview", "timestamp": datetime(2021, 5, 4, 10)},
                    ]
                },
                self.team,
            )

            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["count"], 1)
            self.assertEqual(
                results[1]["average_conversion_time"], 3600
            )  # one hour to convert, disregard the incomplete tries
            self.assertEqual(results[1]["median_conversion_time"], 3600)

            # check ordering of people in every step
            self.assertCountEqual(self._get_actor_ids_at_step(query, 1), [people["person1"].uuid])

        def test_funnel_step_conversion_times(self):
            query = FunnelsQuery(
                dateRange=DateRange(
                    date_from="2020-01-01",
                    date_to="2020-01-08",
                ),
                funnelsFilter=FunnelsFilter(
                    funnelOrderType=funnel_order_type,
                ),
                series=[
                    EventsNode(
                        event="sign up",
                        name="sign up",
                    ),
                    EventsNode(
                        event="play movie",
                        name="play movie",
                    ),
                    EventsNode(
                        event="buy",
                        name="buy",
                    ),
                ],
            )

            journeys_for(
                {
                    "person1": [
                        {"event": "sign up", "timestamp": datetime(2020, 1, 1, 12)},
                        {"event": "play movie", "timestamp": datetime(2020, 1, 1, 13)},
                        {"event": "buy", "timestamp": datetime(2020, 1, 1, 15)},
                    ],
                    "person2": [
                        {"event": "sign up", "timestamp": datetime(2020, 1, 2, 14)},
                        {"event": "play movie", "timestamp": datetime(2020, 1, 2, 16)},
                    ],
                    "person3": [
                        {"event": "sign up", "timestamp": datetime(2020, 1, 2, 14)},
                        {"event": "play movie", "timestamp": datetime(2020, 1, 2, 16)},
                        {"event": "buy", "timestamp": datetime(2020, 1, 2, 17)},
                    ],
                },
                self.team,
            )

            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["average_conversion_time"], None)
            self.assertEqual(results[1]["average_conversion_time"], 6000)
            self.assertEqual(results[2]["average_conversion_time"], 5400)

            self.assertEqual(results[0]["median_conversion_time"], None)
            self.assertEqual(results[1]["median_conversion_time"], 7200)
            self.assertEqual(results[2]["median_conversion_time"], 5400)

        def test_funnel_times_with_different_conversion_windows(self):
            query = FunnelsQuery(
                dateRange=DateRange(
                    date_from="2020-01-01",
                    date_to="2020-01-14",
                ),
                funnelsFilter=FunnelsFilter(
                    funnelOrderType=funnel_order_type,
                ),
                series=[
                    EventsNode(
                        event="user signed up",
                        name="user signed up",
                    ),
                    EventsNode(
                        event="pageview",
                        name="pageview",
                    ),
                ],
            )

            # event
            people = journeys_for(
                {
                    "stopped_after_signup1": [
                        {
                            "event": "user signed up",
                            "timestamp": datetime(2020, 1, 2, 14),
                        },
                        {"event": "pageview", "timestamp": datetime(2020, 1, 2, 14, 5)},
                    ],
                    "stopped_after_signup2": [
                        {
                            "event": "user signed up",
                            "timestamp": datetime(2020, 1, 2, 14, 3),
                        }
                    ],
                    "stopped_after_signup3": [
                        {
                            "event": "user signed up",
                            "timestamp": datetime(2020, 1, 2, 12),
                        },
                        {
                            "event": "pageview",
                            "timestamp": datetime(2020, 1, 2, 12, 15),
                        },
                    ],
                },
                self.team,
            )

            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["count"], 3)
            self.assertEqual(results[1]["count"], 2)
            self.assertEqual(results[1]["average_conversion_time"], 600)

            self.assertCountEqual(
                self._get_actor_ids_at_step(query, 1),
                [
                    people["stopped_after_signup1"].uuid,
                    people["stopped_after_signup2"].uuid,
                    people["stopped_after_signup3"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(query, 2),
                [
                    people["stopped_after_signup1"].uuid,
                    people["stopped_after_signup3"].uuid,
                ],
            )

            query = FunnelsQuery(
                dateRange=DateRange(
                    date_from="2020-01-01",
                    date_to="2020-01-14",
                ),
                funnelsFilter=FunnelsFilter(
                    funnelOrderType=funnel_order_type,
                    funnelWindowInterval=5,
                    funnelWindowIntervalUnit=FunnelConversionWindowTimeUnit.MINUTE,
                ),
                series=[
                    EventsNode(
                        event="user signed up",
                        name="user signed up",
                    ),
                    EventsNode(
                        event="pageview",
                        name="pageview",
                    ),
                ],
            )

            result4 = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertNotEqual(results, result4)
            self.assertEqual(result4[0]["count"], 3)
            self.assertEqual(result4[1]["count"], 1)
            self.assertEqual(result4[1]["average_conversion_time"], 300)

            self.assertCountEqual(
                self._get_actor_ids_at_step(query, 1),
                [
                    people["stopped_after_signup1"].uuid,
                    people["stopped_after_signup2"].uuid,
                    people["stopped_after_signup3"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(query, 2),
                [people["stopped_after_signup1"].uuid],
            )

    return TestFunnelConversionTime
