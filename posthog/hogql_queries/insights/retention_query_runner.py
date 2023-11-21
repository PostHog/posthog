from datetime import datetime, timedelta
from math import ceil
from typing import Optional, Any, Dict

from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL, REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.caching.utils import is_stale
from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team
from posthog.models.filters.mixins.utils import cached_property
from posthog.queries.retention.types import CohortKey
from posthog.queries.util import correct_result_for_sampling
from posthog.schema import (
    HogQLQueryModifiers,
    RetentionQuery,
    RetentionQueryResponse,
)


class RetentionQueryRunner(QueryRunner):
    query: RetentionQuery
    query_type = RetentionQuery

    def __init__(
        self,
        query: RetentionQuery | Dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        in_export_context: Optional[bool] = None,
    ):
        super().__init__(query, team=team, timings=timings, modifiers=modifiers, in_export_context=in_export_context)

    def returning_event_query(self) -> ast.SelectQuery:
        return parse_select(
            """
            SELECT toStartOfDay(toTimeZone(toDateTime(e.timestamp), 'US/Pacific')) AS event_date,
                                                    e.person_id                                                            as target
                                             FROM events e
                                             WHERE e.event = '$pageview'
                                               AND notEmpty(e.person_id)
                                             GROUP BY target, event_date
            """
        )

    def target_event_query(self) -> ast.SelectQuery:
        return parse_select(
            """
            SELECT min(toStartOfDay(e.timestamp)) as event_date,
                                                    e.person_id                                                                 as target,
                                                    [
                                                        dateDiff(
                                                                'Day',
                                                                toStartOfDay({date_from}),
                                                                toStartOfDay(min(e.timestamp))
                                                        )
                                                        ]                                                                       as breakdown_values
                                             FROM events e
                                             WHERE e.event = '$pageview'
                                               AND notEmpty(e.person_id)
                                             GROUP BY target
            """,
            placeholders=self.query_date_range.to_placeholders(),
        )

    def actor_query(self) -> ast.SelectQuery:
        placeholders = {
            "returning_event_query": self.returning_event_query(),
            "target_event_query": self.target_event_query(),
            "period": ast.Constant(value="Day"),
            "breakdown_values_filter": ast.Constant(value=None),
            "selected_interval": ast.Constant(value=None),
        }
        return parse_select(
            """
            SELECT DISTINCT breakdown_values,
                            intervals_from_base,
                            actor_id

            FROM (
                     SELECT target_event.breakdown_values AS breakdown_values,
                            dateDiff(
                                    {period},
                                    target_event.event_date,
                                    returning_event.event_date
                            )                             AS intervals_from_base,
                            returning_event.target        AS actor_id

                     FROM {target_event_query} AS target_event
                              JOIN {returning_event_query} AS returning_event
                                   ON returning_event.target = target_event.target

                     WHERE returning_event.event_date > target_event.event_date

                     UNION ALL

                     SELECT target_event.breakdown_values AS breakdown_values,
                            0                             AS intervals_from_base,
                            target_event.target           AS actor_id

                     FROM {target_event_query} AS target_event
                     )

            WHERE ({breakdown_values_filter} is NULL OR breakdown_values = {breakdown_values_filter})
              AND ({selected_interval} is NULL OR intervals_from_base = {selected_interval})
            """,
            placeholders,
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        placeholders = {
            "actor_query": self.actor_query(),
        }
        with self.timings.measure("retention_query"):
            retention_query = parse_select(
                """
                    SELECT actor_activity.breakdown_values         AS breakdown_values,
                           actor_activity.intervals_from_base      AS intervals_from_base,
                           COUNT(DISTINCT actor_activity.actor_id) AS count

                    FROM {actor_query} AS actor_activity

                    GROUP BY breakdown_values,
                             intervals_from_base

                    ORDER BY breakdown_values,
                             intervals_from_base
                """,
                placeholders,
                timings=self.timings,
            )
        return retention_query

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=None,
            now=datetime.now(),
        )

    def _is_stale(self, cached_result_package):
        date_to = self.query_date_range.date_to()
        interval = self.query_date_range.interval_name
        return is_stale(self.team, date_to, interval, cached_result_package)

    def _refresh_frequency(self):
        date_to = self.query_date_range.date_to()
        date_from = self.query_date_range.date_from()
        interval = self.query_date_range.interval_name

        delta_days: Optional[int] = None
        if date_from and date_to:
            delta = date_to - date_from
            delta_days = ceil(delta.total_seconds() / timedelta(days=1).total_seconds())

        refresh_frequency = BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL
        if interval == "hour" or (delta_days is not None and delta_days <= 7):
            # The interval is shorter for short-term insights
            refresh_frequency = REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL

        return refresh_frequency

    def calculate(self) -> RetentionQueryResponse:
        query = self.to_query()
        hogql = to_printed_hogql(query, self.team.pk)

        response = execute_hogql_query(
            query_type="RetentionQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )

        result_dict = {
            CohortKey(tuple(breakdown_values), intervals_from_base): {
                "count": correct_result_for_sampling(count, self.query.samplingFactor),
                "people": [],
                "people_url": "",  # TODO: URL
            }
            for (breakdown_values, intervals_from_base, count) in response.results
        }

        results = [
            {
                "values": [
                    result_dict.get(CohortKey((first_day,), day), {"count": 0, "people": []})
                    for day in range(self.query.retentionFilter.total_intervals - first_day)
                ],
                "label": "{} {}".format(self.query.retentionFilter.period, first_day),
                "date": self.query_date_range.date_from(),
                # + RetentionFilter.determine_time_delta(first_day, filter.period)[0],
                "people_url": "",  # TODO: URL
            }
            for first_day in range(self.query.retentionFilter.total_intervals)
        ]

        return RetentionQueryResponse(results=results, timings=response.timings, hogql=hogql)
