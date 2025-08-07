from dataclasses import dataclass
import structlog

from uuid import UUID
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
    ErrorTrackingIssueCorrelationQuery,
    ErrorTrackingIssueCorrelationQueryResponse,
    CachedErrorTrackingIssueCorrelationQueryResponse,
    DateRange,
)
from django.db.models import QuerySet
from posthog.models.error_tracking import ErrorTrackingIssue
from posthog.api.error_tracking import ErrorTrackingIssueSerializer
from posthog.hogql.parser import parse_select
import datetime

logger = structlog.get_logger(__name__)


@dataclass
class VolumeOptions:
    date_range: DateRange
    resolution: int


class ErrorTrackingIssueCorrelationQueryRunner(QueryRunner):
    query: ErrorTrackingIssueCorrelationQuery
    response: ErrorTrackingIssueCorrelationQueryResponse
    cached_response: CachedErrorTrackingIssueCorrelationQueryResponse
    paginator: HogQLHasMorePaginator
    date_from: datetime.datetime
    date_to: datetime.datetime

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=50,
            offset=0,
        )

    def calculate(self):
        with self.timings.measure("error_tracking_query_hogql_execute"):
            query_result = self.paginator.execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                query_type="ErrorTrackingIssueCorrelationQuery",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        columns: list[str] = query_result.columns or []
        results = self.results(query_result.results)

        return ErrorTrackingIssueCorrelationQueryResponse(
            columns=columns,
            results=results,
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    def results(self, rows: list[tuple[str, list[UUID], list[int], list[int], list[int], list[int]]]) -> list[dict]:
        issue_ids: set[str] = set()
        correlations: dict[str, dict[str, float]] = {}

        for row in rows:
            event, issue_uuids, issue_both, issue_success_only, issue_exception_only, issue_neither = row
            issues = list(zip(issue_uuids, issue_both, issue_success_only, issue_exception_only, issue_neither))

            for issue in issues:
                uuid, both, success_only, exception_only, neither = issue

                if not (both > 0 and success_only > 0 and exception_only > 0 and neither > 0):
                    continue

                issue_ids.add(str(uuid))
                odds_ratio = (both * neither) / (success_only * exception_only)

                issue_correlation = correlations.setdefault(str(uuid), {})
                issue_correlation[event] = odds_ratio

        issues = self.fetch_issues(list(issue_ids))

        results = []
        for issue in issues:
            issue_correlations = correlations.get(issue["id"], {})  # type: ignore
            for event, odds_ratio in issue_correlations.items():
                results.append({**issue, "correlation_score": odds_ratio, "correlation_event": event})  # type: ignore

        return sorted(results, key=lambda r: r["correlation_score"], reverse=True)

    def fetch_issues(self, ids: list[str]):
        queryset: QuerySet[ErrorTrackingIssue] = (
            ErrorTrackingIssue.objects.with_first_seen()
            .select_related("assignment")
            .filter(id__in=ids, team=self.team, status=ErrorTrackingIssue.Status.ACTIVE)
        )
        return ErrorTrackingIssueSerializer(queryset, many=True).data

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """WITH issue_list AS (
SELECT groupUniqArray(issue_id) as value
    FROM events
    WHERE timestamp > now() - INTERVAL 12 HOUR AND notEmpty(events.$session_id) AND issue_id IS NOT NULL AND event = '$exception'
)
SELECT
    '{self.query.events[0]}' as event,
    (SELECT * FROM issue_list) as issue_ids,
    sumForEach(both) as both,
    sumForEach(success_only) as success_only,
    sumForEach(exception_only) as exception_only,
    sumForEach(neither) as neither
FROM(
    SELECT
        $session_id,
        minIf(toNullable(timestamp), event='{self.query.events[0]}') as earliest_success_event,
        minForEach(arrayMap(x -> (if(x = issue_id, toNullable(timestamp), NULL)), (SELECT * FROM issue_list))) as earliest_exceptions,
        arrayMap(x -> if(x IS NOT NULL AND earliest_success_event IS NOT NULL AND x < earliest_success_event, 1, 0), earliest_exceptions) AS both,
        arrayMap(x -> if(x IS NULL AND earliest_success_event IS NOT NULL, 1, 0), earliest_exceptions) AS success_only,
        arrayMap(x -> if(x IS NOT NULL AND earliest_success_event IS NULL, 1, 0), earliest_exceptions) AS exception_only,
        arrayMap(x -> if(x IS NULL AND earliest_success_event IS NULL, 1, 0), earliest_exceptions) AS neither
    FROM events
    WHERE
        timestamp > now() - INTERVAL 12 HOUR AND
        notEmpty(events.$session_id)
    GROUP BY $session_id
)"""
        )

        # return parse_select(
        #     """SELECT
        #             event,
        #             any(issue_ids),
        #             sumForEach(both) as both,
        #             sumForEach(success_only) as success_only,
        #             sumForEach(exception_only) as exception_only,
        #             sumForEach(neither) as neither
        #         FROM(
        #             WITH issue_list AS (
        #                 SELECT groupUniqArray(issue_id) as value
        #                 FROM events
        #                 WHERE timestamp > now() - INTERVAL 6 HOUR AND notEmpty(events.$session_id) AND issue_id IS NOT NULL AND event = '$exception'
        #             )
        #             select
        #                 event,
        #                 $session_id,
        #                 (SELECT * FROM issue_list) AS issue_ids,
        #                 minIf(toNullable(timestamp), event != '$exception') as earliest_success_event,
        #                 minForEach(arrayMap(x -> (if(x = issue_id, toNullable(timestamp), NULL)), issue_ids)) as earliest_exceptions,
        #                 arrayMap(x -> if(x IS NOT NULL AND earliest_success_event IS NOT NULL AND x < earliest_success_event, 1, 0), earliest_exceptions) AS both,
        #                 arrayMap(x -> if(x IS NULL AND earliest_success_event IS NOT NULL, 1, 0), earliest_exceptions) AS success_only,
        #                 arrayMap(x -> if(x IS NOT NULL AND earliest_success_event IS NULL, 1, 0), earliest_exceptions) AS exception_only,
        #                 arrayMap(x -> if(x IS NULL AND earliest_success_event IS NULL, 1, 0), earliest_exceptions) AS neither
        #             from events
        #             where
        #                 timestamp > now() - INTERVAL 6 HOUR AND
        #                 notEmpty(events.$session_id) AND
        #                 event in ('$pageview', '$pageleave')
        #             group by $session_id, event
        #         )
        #         group by event
        #     """
        # )
