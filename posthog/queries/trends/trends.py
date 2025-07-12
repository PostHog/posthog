import copy
import threading
import posthoganalytics
from datetime import datetime, timedelta
from itertools import accumulate
from typing import Any, Optional, cast
from collections.abc import Callable
from zoneinfo import ZoneInfo

from dateutil import parser

from posthog.clickhouse.query_tagging import get_query_tags, QueryTags, update_tags
from posthog.constants import (
    INSIGHT_LIFECYCLE,
    NON_BREAKDOWN_DISPLAY_TYPES,
    TREND_FILTER_TYPE_ACTIONS,
    TRENDS_CUMULATIVE,
    TRENDS_LIFECYCLE,
    TRENDS_LINEAR,
)
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.team import Team
from posthog.queries.base import handle_compare
from posthog.queries.insight import insight_sync_execute
from posthog.queries.trends.breakdown import TrendsBreakdown
from posthog.queries.trends.formula import TrendsFormula
from posthog.queries.trends.lifecycle import Lifecycle
from posthog.queries.trends.total_volume import TrendsTotalVolume
from posthog.utils import generate_cache_key, get_safe_cache


class Trends(TrendsTotalVolume, Lifecycle, TrendsFormula):
    def _get_sql_for_entity(self, filter: Filter, team: Team, entity: Entity) -> tuple[str, str, dict, Callable]:
        if filter.breakdown and filter.display not in NON_BREAKDOWN_DISPLAY_TYPES:
            query_type = "trends_breakdown"
            sql, params, parse_function = TrendsBreakdown(
                entity,
                filter,
                team,
                person_on_events_mode=team.person_on_events_mode,
                add_person_urls=not self.is_csv_export,
            ).get_query()
        elif filter.insight == INSIGHT_LIFECYCLE or filter.shown_as == TRENDS_LIFECYCLE:
            query_type = "trends_lifecycle"
            sql, params, parse_function = self._format_lifecycle_query(entity, filter, team)
        else:
            query_type = "trends_total_volume"
            sql, params, parse_function = self._total_volume_query(entity, filter, team)

        return query_type, sql, params, parse_function

    # Use cached result even on refresh if team has strict caching enabled
    def get_cached_result(self, filter: Filter, team: Team) -> Optional[list[dict[str, Any]]]:
        if not team.strict_caching_enabled or filter.breakdown or filter.display != TRENDS_LINEAR:
            return None

        cache_key = generate_cache_key(f"{filter.toJSON()}_{team.pk}")
        cached_result_package = get_safe_cache(cache_key)
        cached_result = (
            cached_result_package.get("result")
            if cached_result_package and isinstance(cached_result_package, dict)
            else None
        )

        if not cached_result:
            return None

        _is_present = self.is_present_timerange(cached_result, filter, team)

        return cached_result if _is_present else None

    # Determine if the current timerange is present in the cache
    def is_present_timerange(self, cached_result: list[dict[str, Any]], filter: Filter, team: Team) -> bool:
        if (
            len(cached_result) > 0
            and cached_result[0].get("days")
            and cached_result[0].get("data")
            and len(cached_result[0]["days"]) > 0
            and len(cached_result[0]["days"]) == len(cached_result[0]["data"])
        ):
            latest_date = cached_result[0]["days"][len(cached_result[0]["days"]) - 1]

            parsed_latest_date = parser.parse(latest_date)
            parsed_latest_date = parsed_latest_date.replace(tzinfo=ZoneInfo(team.timezone))
            _is_present = is_filter_date_present(filter, parsed_latest_date)
        else:
            _is_present = False

        return _is_present

    # Use a condensed filter if a cached result exists in the current timerange
    def adjusted_filter(self, filter: Filter, team: Team) -> tuple[Filter, Optional[dict[str, Any]]]:
        cached_result = self.get_cached_result(filter, team)

        new_filter = filter.shallow_clone({"date_from": interval_unit(filter.interval)}) if cached_result else filter

        label_to_payload = {}
        if cached_result:
            for payload in cached_result:
                label_to_payload[f'{payload["label"]}_{payload["action"]["order"]}'] = payload

        return new_filter, label_to_payload

    def merge_results(
        self,
        result,
        cached_result: Optional[dict[str, Any]],
        entity_order: int,
        filter: Filter,
        team: Team,
    ):
        if cached_result and filter.display != TRENDS_CUMULATIVE:
            new_res = []

            for payload in result:
                cached_series = cached_result.pop(f'{payload["label"]}_{entity_order}')
                data = cached_series["data"]
                data.pop()
                data.append(payload["data"].pop())
                cached_series["data"] = data
                new_res.append(cached_series)

            return new_res, cached_result
        elif filter.display == TRENDS_CUMULATIVE:
            return self._handle_cumulative(result), {}
        else:
            return result, {}

    def _run_query(self, filter: Filter, team: Team, entity: Entity) -> list[dict[str, Any]]:
        adjusted_filter, cached_result = self.adjusted_filter(filter, team)
        with posthoganalytics.new_context():
            query_type, sql, params, parse_function = self._get_sql_for_entity(adjusted_filter, team, entity)
            posthoganalytics.tag("filter", filter.to_dict())
            posthoganalytics.tag("team_id", str(team.pk))
            query_params = {**params, **adjusted_filter.hogql_context.values}
            posthoganalytics.tag("query", {"sql": sql, "params": query_params})
            result = insight_sync_execute(
                sql,
                query_params,
                settings={"timeout_before_checking_execution_speed": 60},
                query_type=query_type,
                filter=adjusted_filter,
                team_id=team.pk,
            )
            result = parse_function(result)
            serialized_data = self._format_serialized(entity, result)
            merged_results, cached_result = self.merge_results(
                serialized_data,
                cached_result,
                entity.order or entity.index,
                filter,
                team,
            )

        if cached_result:
            for value in cached_result.values():
                merged_results.append(value)

        return merged_results

    def _run_query_for_threading(
        self,
        result: list,
        index: int,
        query_type,
        sql,
        params,
        query_tags: QueryTags,
        filter: Filter,
        team_id: int,
    ):
        update_tags(query_tags)
        with posthoganalytics.new_context():
            posthoganalytics.tag("query", {"sql": sql, "params": params})
            result[index] = insight_sync_execute(sql, params, query_type=query_type, filter=filter, team_id=team_id)

    def _run_parallel(self, filter: Filter, team: Team) -> list[dict[str, Any]]:
        result: list[Optional[list[dict[str, Any]]]] = [None] * len(filter.entities)
        parse_functions: list[Optional[Callable]] = [None] * len(filter.entities)
        sql_statements_with_params: list[tuple[Optional[str], dict]] = [(None, {})] * len(filter.entities)
        cached_result = None
        jobs = []

        for entity in filter.entities:
            adjusted_filter, cached_result = self.adjusted_filter(filter, team)
            query_type, sql, params, parse_function = self._get_sql_for_entity(adjusted_filter, team, entity)
            parse_functions[entity.index] = parse_function
            query_params = {**params, **adjusted_filter.hogql_context.values}
            sql_statements_with_params[entity.index] = (sql, query_params)
            thread = threading.Thread(
                target=self._run_query_for_threading,
                args=(
                    result,
                    entity.index,
                    query_type,
                    sql,
                    query_params,
                    get_query_tags().model_copy(deep=True),
                    adjusted_filter,
                    team.pk,
                ),
            )
            jobs.append(thread)

        # Start the threads (i.e. calculate the random number lists)
        for j in jobs:
            j.start()

        # Ensure all of the threads have finished
        for j in jobs:
            j.join()

        # Parse results for each thread
        with posthoganalytics.new_context():
            posthoganalytics.tag("filter", filter.to_dict())
            posthoganalytics.tag("team_id", str(team.pk))
            for entity in filter.entities:
                serialized_data = cast(list[Callable], parse_functions)[entity.index](result[entity.index])
                serialized_data = self._format_serialized(entity, serialized_data)
                merged_results, cached_result = self.merge_results(
                    serialized_data,
                    cached_result,
                    entity.order or entity.index,
                    filter,
                    team,
                )
                result[entity.index] = merged_results

        # flatten results
        flat_results: list[dict[str, Any]] = []
        for item in result:
            for flat in cast(list[dict[str, Any]], item):
                flat_results.append(flat)

            if cached_result:
                for value in cached_result.values():
                    flat_results.append(value)

        return flat_results

    def run(self, filter: Filter, team: Team, is_csv_export: bool = False, *args, **kwargs) -> list[dict[str, Any]]:
        self.is_csv_export = is_csv_export
        actions = Action.objects.filter(team__project_id=team.project_id).order_by("-id")
        if len(filter.actions) > 0:
            actions = Action.objects.filter(
                pk__in=[entity.id for entity in filter.actions], team__project_id=team.project_id
            )

        if filter.formula:
            return handle_compare(filter, self._run_formula_query, team)

        for entity in filter.entities:
            if entity.type == TREND_FILTER_TYPE_ACTIONS and entity.id is not None:
                try:
                    entity.name = actions.get(id=entity.id).name
                except Action.DoesNotExist:
                    return []

        if len(filter.entities) == 1 or filter.compare:
            result = []
            for entity in filter.entities:
                result.extend(handle_compare(filter, self._run_query, team, entity=entity))
        else:
            result = self._run_parallel(filter, team)

        return result

    def _format_serialized(self, entity: Entity, result: list[dict[str, Any]]):
        serialized_data = []

        serialized: dict[str, Any] = {
            "action": entity.to_dict(),
            "label": entity.name,
            "count": 0,
            "data": [],
            "labels": [],
            "days": [],
        }

        for queried_metric in result:
            serialized_copy = copy.deepcopy(serialized)
            serialized_copy.update(queried_metric)
            serialized_data.append(serialized_copy)

        return serialized_data

    def _handle_cumulative(self, entity_metrics: list) -> list[dict[str, Any]]:
        for metrics in entity_metrics:
            metrics.update(data=list(accumulate(metrics["data"])))
        return entity_metrics


def is_filter_date_present(filter: Filter, latest_cached_datetime: datetime) -> bool:
    diff = filter.date_to - latest_cached_datetime

    if filter.interval == "hour":
        return diff < timedelta(hours=1)
    elif filter.interval == "day":
        return diff < timedelta(days=1)
    elif filter.interval == "week":
        return diff < timedelta(weeks=1)
    elif filter.interval == "month":
        return diff < timedelta(days=30)


def interval_unit(interval: str) -> str:
    if interval == "hour":
        return "-1hr"
    if interval == "day":
        return "-1d"
    elif interval == "week":
        return "-1w"
    elif interval == "month":
        return "-1m"
    else:
        raise ValueError("Invalid interval")
