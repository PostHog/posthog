from datetime import date, datetime, timedelta
from typing import Union, cast
from uuid import uuid4

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel_trends import ClickhouseFunnelTrends
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS, TRENDS_LINEAR
from posthog.models.filters import Filter
from posthog.models.filters.mixins.funnel_window_days import FunnelWindowDaysMixin
from posthog.models.person import Person
from posthog.test.base import APIBaseTest

FORMAT_TIME = "%Y-%m-%d 00:00:00"

TIME_0 = "2021-06-03 13:42:00"
TIME_1 = "2021-06-07 00:00:00"
TIME_3 = "2021-06-07 19:00:00"
TIME_4 = "2021-06-08 02:00:00"
TIME_99 = "2021-06-13 23:59:59"

STEP_1_EVENT = "step one"
STEP_2_EVENT = "step two"
STEP_3_EVENT = "step three"
USER_A_DISTINCT_ID = "user a"


def build_funnel_trend_v2_query(
    team_id: int, start: Union[str, datetime], end: Union[str, datetime], event_1: str, event_2: str, event_3: str
) -> str:
    start_string: str = start if isinstance(start, str) else start.strftime(FORMAT_TIME)
    end_string: str = end if isinstance(end, str) else end.strftime(FORMAT_TIME)

    join_distinct_id_part = f"""
    -- join distinct_id
    JOIN (
        SELECT person_id, distinct_id
        FROM (
            SELECT *
            FROM person_distinct_id
            JOIN (
                SELECT distinct_id, max(_offset) AS _offset
                FROM person_distinct_id
                WHERE team_id = {team_id}
                GROUP BY distinct_id
            ) AS person_max
            ON person_distinct_id.distinct_id = person_max.distinct_id
            AND person_distinct_id._offset = person_max._offset
            WHERE team_id = {team_id}
        )
        WHERE team_id = {team_id}
    ) AS pid
    ON pid.distinct_id = events.distinct_id
    """

    funnel_steps_query_part_3_steps = f"""
    -- calculate funnel steps
    SELECT day, countIf(furthest = 1) one_step, countIf(furthest = 2) two_step, countIf(furthest=3) three_step FROM (
        SELECT person_id, toStartOfDay(time_of_event) day, max(steps) AS furthest FROM (
            SELECT *,
            if(rounded_3_date >= rounded_2_date AND rounded_2_date >= latest_1 AND rounded_2_date <= latest_1 + INTERVAL 2 DAY AND rounded_3_date >= latest_1 AND rounded_3_date <= latest_1 + INTERVAL 2 DAY, 3, if(rounded_2_date >= latest_1 AND rounded_2_date <= latest_1 + INTERVAL 2 DAY, 2, 1)) AS steps FROM (
                SELECT
                    person_id,
                    step_1,
                    latest_1,
                    rounded_2,
                    rounded_2_date,
                    rounded_3,
                    min(latest_3) over (PARTITION by person_id ORDER BY time_of_event DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) rounded_3_date,
                    time_of_event
                FROM (
                    SELECT 
                        person_id,
                        step_1,
                        latest_1,
                        rounded_2,
                        rounded_2_date,
                        rounded_3,
                        if(rounded_3_date < rounded_2_date, NULL, rounded_3_date) AS latest_3,
                        time_of_event
                    FROM (
                        SELECT 
                            person_id, 
                            step_1, 
                            latest_1, 
                            step_2 AS rounded_2, 
                            min(latest_2) over (PARTITION by person_id ORDER BY time_of_event DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) rounded_2_date, 
                            step_3 AS rounded_3, 
                            min(latest_3) over (PARTITION by person_id ORDER BY time_of_event DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) rounded_3_date, 
                            time_of_event 
                        FROM (
                            SELECT 
                            pid.person_id AS person_id,
                            if(event = '{event_1}', 1, 0) AS step_1,
                            if(step_1 = 1, timestamp, null) AS latest_1,
                            if(event = '{event_2}', 1, 0) AS step_2,
                            if(step_2 = 1, timestamp, null) AS latest_2,
                            if(event = '{event_3}', 1, 0) AS step_3,
                            if(step_3 = 1, timestamp, null) AS latest_3,
                            if(step_1 = 1 OR step_2 = 1 OR step_3 = 1, timestamp, null) AS time_of_event
                            FROM events
                            {join_distinct_id_part}
                            WHERE team_id = {team_id}
                            AND events.timestamp >= '{start_string}'
                            AND events.timestamp <= '{end_string}'
                            AND isNotNull(time_of_event)
                            ORDER BY time_of_event ASC
                        )
                    )
                )
            )
            WHERE step_1 = 1
        ) GROUP BY person_id, day
    ) GROUP BY day
    """

    funnel_trends_query_complete_3_steps = f"""
    -- calculate funnel trends using steps
    SELECT toStartOfDay(toDateTime('{start_string}') - number * 86400) AS day, total, completed, percentage
    FROM numbers(8) AS num
    LEFT OUTER JOIN (
        SELECT day, one_step + three_step AS total, three_step AS completed, completed / total AS percentage FROM (
            {funnel_steps_query_part_3_steps}
        )
    ) data
    ON data.day = day 
    ORDER BY day ASC
    SETTINGS allow_experimental_window_functions = 1
    """

    return funnel_trends_query_complete_3_steps


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestFunnelTrends(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def test_no_event_in_period(self):
        _create_person(distinct_ids=[USER_A_DISTINCT_ID], team=self.team)

        _create_event(event=STEP_1_EVENT, distinct_id=USER_A_DISTINCT_ID, team=self.team, timestamp=TIME_0)

        sql = build_funnel_trend_v2_query(self.team.pk, TIME_1, TIME_99, STEP_1_EVENT, STEP_2_EVENT, STEP_3_EVENT)
        results = sync_execute(sql)
        self.assertListEqual(
            cast(list, results),
            [
                (datetime(2021, 5, 31, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 1, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 2, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 3, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 4, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 5, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 6, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 7, 0, 0), 0, 0, 0.0),
            ],
        )

    def test_only_one_user_reached_one_step(self):
        _create_person(distinct_ids=[USER_A_DISTINCT_ID], team=self.team)

        _create_event(event=STEP_1_EVENT, distinct_id=USER_A_DISTINCT_ID, team=self.team, timestamp=TIME_3)

        sql = build_funnel_trend_v2_query(self.team.pk, TIME_1, TIME_99, STEP_1_EVENT, STEP_2_EVENT, STEP_3_EVENT)
        results = sync_execute(sql)
        self.assertListEqual(
            cast(list, results),
            [
                (datetime(2021, 5, 31, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 1, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 2, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 3, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 4, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 5, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 6, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 7, 0, 0), 1, 0, 0.0),
            ],
        )
