from typing import Dict, Any

from freezegun import freeze_time

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.team import WeekStartDay
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
)


class TestInsightActorsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _create_test_groups(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:1",
            properties={"name": "org1"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:2",
            properties={"name": "org2"},
        )

    def _create_events(self, data, event="$pageview"):
        for id, timestamps in data:
            with freeze_time(timestamps[0]):
                _create_person(
                    team_id=self.team.pk,
                    distinct_ids=[id],
                    properties={
                        "name": id,
                        **({"email": "test@posthog.com"} if id == "p1" else {}),
                    },
                )
            for timestamp in timestamps:
                _create_event(
                    team=self.team, event=event, distinct_id=id, timestamp=timestamp, properties={"$group_0": "org:1"}
                )

    def _create_test_events(self):
        self._create_events(
            data=[
                (
                    "p1",
                    [
                        "2020-01-11T12:00:00Z",
                        "2020-01-12T12:00:00Z",
                        "2020-01-13T12:00:00Z",
                        "2020-01-15T12:00:00Z",
                        "2020-01-17T12:00:00Z",
                        "2020-01-19T12:00:00Z",
                    ],
                ),
                ("p2", ["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"]),
                ("p3", ["2020-01-12T12:00:00Z"]),
                ("p4", ["2020-01-15T12:00:00Z"]),
            ]
        )

    def select(self, query: str, placeholders: Dict[str, Any] = {}):
        return execute_hogql_query(
            query=query,
            team=self.team,
            placeholders=placeholders,
        )

    def test_insight_persons_lifecycle_query(self):
        self._create_test_events()
        self.team.timezone = "US/Pacific"
        self.team.save()

        date_from = "2020-01-09"
        date_to = "2020-01-19"

        response = self.select(
            """
            select * from (
                <ActorsQuery select={['properties.name as n']}>
                    <InsightActorsQuery day='2020-01-12' status='returning'>
                        <LifecycleQuery
                            dateRange={<DateRange date_from={{date_from}} date_to={{date_to}} />}
                            series={[<EventsNode event='$pageview' math='total' />]}
                        />
                    </InsightActorsQuery>
                </ActorsQuery>
            )
            """,
            {"date_from": ast.Constant(value=date_from), "date_to": ast.Constant(value=date_to)},
        )

        self.assertEqual([("p1",)], response.results)

    def test_insight_persons_lifecycle_query_week_monday(self):
        self._create_test_events()
        self.team.timezone = "US/Pacific"
        self.team.week_start_day = WeekStartDay.MONDAY
        self.team.save()

        date_from = "2020-01-09"
        date_to = "2020-01-19"

        response = self.select(
            """
            select * from (
                <ActorsQuery select={['properties.name as n']}>
                    <InsightActorsQuery day='2020-01-13' status='returning'>
                        <LifecycleQuery
                            interval='week'
                            dateRange={<DateRange date_from={{date_from}} date_to={{date_to}} />}
                            series={[<EventsNode event='$pageview' math='total' />]}
                        />
                    </InsightActorsQuery>
                </ActorsQuery>
            )
            """,
            {"date_from": ast.Constant(value=date_from), "date_to": ast.Constant(value=date_to)},
        )

        self.assertEqual([("p1",)], response.results)

    def test_insight_persons_lifecycle_query_week_sunday(self):
        self._create_test_events()
        self.team.timezone = "US/Pacific"
        self.team.week_start_day = WeekStartDay.SUNDAY
        self.team.save()

        date_from = "2020-01-09"
        date_to = "2020-01-19"

        response = self.select(
            """
            select * from (
                <ActorsQuery select={['properties.name as n']}>
                    <InsightActorsQuery day='2020-01-12' status='returning'>
                        <LifecycleQuery
                            interval='week'
                            dateRange={<DateRange date_from={{date_from}} date_to={{date_to}} />}
                            series={[<EventsNode event='$pageview' math='total' />]}
                        />
                    </InsightActorsQuery>
                </ActorsQuery>
            )
            """,
            {"date_from": ast.Constant(value=date_from), "date_to": ast.Constant(value=date_to)},
        )

        self.assertEqual([("p1",), ("p2",)], response.results)

    def test_insight_persons_stickiness_query(self):
        self._create_test_events()
        self.team.timezone = "US/Pacific"
        self.team.save()

        response = self.select(
            """
            select * from (
                <ActorsQuery select={['properties.name']}>
                    <InsightActorsQuery day={2}>
                        <StickinessQuery
                            dateRange={<DateRange date_from='2020-01-09' date_to='2020-01-19' />}
                            series={[<EventsNode event='$pageview' />]}
                        />
                    </InsightActorsQuery>
                </ActorsQuery>
            )
            """
        )

        self.assertEqual([("p2",)], response.results)

    def test_insight_persons_stickiness_groups_query(self):
        self._create_test_groups()
        self._create_test_events()
        self.team.timezone = "US/Pacific"
        self.team.save()

        response = self.select(
            """
            select * from (
                <ActorsQuery select={['properties.name']}>
                    <InsightActorsQuery day={7}>
                        <StickinessQuery
                            dateRange={<DateRange date_from='2020-01-01' date_to='2020-01-19' />}
                            series={[<EventsNode event='$pageview' math='unique_group' math_group_type_index={0} />]}
                        />
                    </InsightActorsQuery>
                </ActorsQuery>
            )
            """
        )

        self.assertEqual([("org1",)], response.results)

    def test_insight_persons_trends_query(self):
        self._create_test_events()
        self.team.timezone = "US/Pacific"
        self.team.save()

        response = self.select(
            """
            select * from (
                <ActorsQuery select={['properties.name']}>
                    <InsightActorsQuery day='2020-01-09'>
                        <TrendsQuery
                            dateRange={<DateRange date_from='2020-01-09' date_to='2020-01-19' />}
                            series={[<EventsNode event='$pageview' />]}
                        />
                    </InsightActorsQuery>
                </ActorsQuery>
            )
            """
        )

        self.assertEqual([("p2",)], response.results)

    def test_insight_persons_trends_groups_query(self):
        self._create_test_groups()
        self._create_test_events()
        self.team.timezone = "US/Pacific"
        self.team.save()

        response = self.select(
            """
            select * from (
                <ActorsQuery select={['properties.name']}>
                    <InsightActorsQuery day='2020-01-09'>
                        <TrendsQuery
                            dateRange={<DateRange date_from='2020-01-01' date_to='2020-01-19' />}
                            series={[<EventsNode event='$pageview' math='unique_group' math_group_type_index={0} />]}
                        />
                    </InsightActorsQuery>
                </ActorsQuery>
            )
            """
        )

        self.assertEqual([("org1",)], response.results)

    def test_insight_persons_funnels_query(self):
        self._create_test_events()
        self.team.timezone = "US/Pacific"
        self.team.save()

        response = self.select(
            """
                select * from (
                    <ActorsQuery select={['properties.name']}>
                        <FunnelsActorsQuery funnelStep={2}>
                            <FunnelsQuery
                                dateRange={<DateRange date_from='2020-01-01' date_to='2020-01-19' />}
                                series={[<EventsNode event='$pageview' />, <EventsNode event='$pageview' />]}
                            />
                        </FunnelsActorsQuery>
                    </ActorsQuery>
                )
                """
        )

        self.assertEqual([("p1",), ("p2",)], response.results)
