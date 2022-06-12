import copy
import threading
from itertools import accumulate
from typing import Any, Callable, Dict, List, Tuple, Union, cast

from django.db.models.query import Prefetch

from posthog.client import sync_execute
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TRENDS_CUMULATIVE, TRENDS_LIFECYCLE
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.team import Team
from posthog.queries.base import handle_compare
from posthog.queries.trends.breakdown import TrendsBreakdown
from posthog.queries.trends.formula import TrendsFormula
from posthog.queries.trends.lifecycle import Lifecycle
from posthog.queries.trends.total_volume import TrendsTotalVolume
from posthog.utils import generate_cache_key, get_safe_cache, relative_date_parse


class Trends(TrendsTotalVolume, Lifecycle, TrendsFormula):
    def _get_sql_for_entity(self, filter: Filter, entity: Entity, team: Team) -> Tuple[str, Dict, Callable]:
        if filter.breakdown:
            sql, params, parse_function = TrendsBreakdown(
                entity, filter, team, using_person_on_events=team.actor_on_events_querying_enabled
            ).get_query()
        elif filter.shown_as == TRENDS_LIFECYCLE:
            sql, params, parse_function = self._format_lifecycle_query(entity, filter, team)
        else:
            sql, params, parse_function = self._total_volume_query(entity, filter, team)

        return sql, params, parse_function

    def _run_query(self, filter: Filter, entity: Entity, team: Team) -> List[Dict[str, Any]]:
        _is_present = is_present_timerange(filter)
        cache_key = generate_cache_key(f"{filter.toJSON()}_{team.pk}")
        cached_result_package = get_safe_cache(cache_key)
        _is_cached = cached_result_package and cached_result_package.get("result")

        truncated_filter = (
            filter.with_data({"date_from": interval_unit(filter.interval)}) if _is_present and _is_cached else filter
        )
        sql, params, parse_function = self._get_sql_for_entity(truncated_filter, entity, team)

        result = sync_execute(sql, params)
        result = parse_function(result)

        if _is_cached:
            new_val = result[0]["data"].pop()
            data = cached_result_package["result"][0]["data"]
            data.pop()
            data.append(new_val)
            cached_result_package["result"][0]["data"] = data
            return cached_result_package["result"]

        serialized_data = self._format_serialized(entity, result)

        if filter.display == TRENDS_CUMULATIVE:
            serialized_data = self._handle_cumulative(serialized_data)
        return serialized_data

    def _run_query_for_threading(self, result: List, index: int, sql, params):
        result[index] = sync_execute(sql, params)

    def _run_parallel(self, filter: Filter, team: Team) -> List[Dict[str, Any]]:
        result: List[Union[None, List[Dict[str, Any]]]] = [None] * len(filter.entities)
        parse_functions: List[Union[None, Callable]] = [None] * len(filter.entities)
        jobs = []

        for entity in filter.entities:
            _is_present = is_present_timerange(filter)
            truncated_filter = (
                filter.with_data({"date_from": interval_unit(filter.interval)}) if _is_present else filter
            )
            sql, params, parse_function = self._get_sql_for_entity(truncated_filter, entity, team)
            parse_functions[entity.index] = parse_function
            thread = threading.Thread(target=self._run_query_for_threading, args=(result, entity.index, sql, params),)
            jobs.append(thread)

        # Start the threads (i.e. calculate the random number lists)
        for j in jobs:
            j.start()

        # Ensure all of the threads have finished
        for j in jobs:
            j.join()

        # Parse results for each thread
        for entity in filter.entities:
            serialized_data = cast(List[Callable], parse_functions)[entity.index](result[entity.index])
            serialized_data = self._format_serialized(entity, serialized_data)

            if filter.display == TRENDS_CUMULATIVE:
                serialized_data = self._handle_cumulative(serialized_data)
            result[entity.index] = serialized_data

        # flatten results
        flat_results: List[Dict[str, Any]] = []
        for item in result:
            for flat in cast(List[Dict[str, Any]], item):
                flat_results.append(flat)

        return flat_results

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        actions = Action.objects.filter(team_id=team.pk).order_by("-id")
        if len(filter.actions) > 0:
            actions = Action.objects.filter(pk__in=[entity.id for entity in filter.actions], team_id=team.pk)
        actions = actions.prefetch_related(Prefetch("steps", queryset=ActionStep.objects.order_by("id")))

        if filter.formula:
            return handle_compare(filter, self._run_formula_query, team)

        for entity in filter.entities:
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
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

    def _format_serialized(self, entity: Entity, result: List[Dict[str, Any]]):
        serialized_data = []

        serialized: Dict[str, Any] = {
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

    def _handle_cumulative(self, entity_metrics: List) -> List[Dict[str, Any]]:
        for metrics in entity_metrics:
            metrics.update(data=list(accumulate(metrics["data"])))
        return entity_metrics


def is_present_timerange(filter: Filter) -> bool:
    interval_diff = interval_unit(filter.interval)
    possible_interval_start = relative_date_parse(interval_diff)

    if possible_interval_start < filter.date_to:
        return True
    else:
        return False


def interval_unit(interval: str) -> str:
    if interval == "hour":
        return "-1hr"
    if interval == "day":
        return "-1d"
    elif interval == "week":
        return "-1w"
    elif interval == "month":
        return "-1m"
    elif interval == "year":
        return "-1y"
    else:
        raise ValueError("Invalid interval")
