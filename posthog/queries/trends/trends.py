import copy
import threading
from itertools import accumulate
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
    cast,
)

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
    _filter: Filter
    _team: Team

    def __init__(self, filter: Filter, team: Team) -> None:
        self._filter = filter
        self._team = team

    def _get_sql_for_entity(self, filter: Filter, entity: Entity) -> Tuple[str, Dict, Callable]:
        if filter.breakdown:
            sql, params, parse_function = TrendsBreakdown(
                entity, filter, self._team, using_person_on_events=self._team.actor_on_events_querying_enabled
            ).get_query()
        elif filter.shown_as == TRENDS_LIFECYCLE:
            sql, params, parse_function = self._format_lifecycle_query(entity, filter, self._team)
        else:
            sql, params, parse_function = self._total_volume_query(entity, filter, self._team)

        return sql, params, parse_function

    def get_cached_result(self, filter: Filter) -> Optional[List[Dict[str, Any]]]:
        cache_key = generate_cache_key(f"{filter.toJSON()}_{self._team.pk}")
        cached_result_package = get_safe_cache(cache_key)
        return cached_result_package.get("result") if cached_result_package else None

    def adjusted_filter(self, filter: Filter) -> Filter:
        _is_present = is_present_timerange(filter)
        _is_cached = self.get_cached_result(filter)

        new_filter = (
            filter.with_data({"date_from": interval_unit(filter.interval)}) if _is_present and _is_cached else filter
        )

        return new_filter

    def merge_results(self, result, filter: Filter):
        cached_result = self.get_cached_result(filter)
        if cached_result and filter.display != TRENDS_CUMULATIVE:
            label_to_val = {}
            new_res = []
            for payload in result:
                label_to_val[payload["label"]] = payload["data"].pop()

            for series in cached_result:
                data = series["data"]
                data.pop()
                data.append(label_to_val[series["label"]])
                series["data"] = data
                new_res.append(series)

            return new_res
        elif filter.display == TRENDS_CUMULATIVE:
            return self._handle_cumulative(result)
        else:
            return result

    def _run_query(self, filter: Filter, team: Team, entity: Entity) -> List[Dict[str, Any]]:
        adjusted_filter = self.adjusted_filter(filter)
        sql, params, parse_function = self._get_sql_for_entity(adjusted_filter, entity)

        result = sync_execute(sql, params)
        result = parse_function(result)
        serialized_data = self._format_serialized(entity, result)
        merged_results = self.merge_results(serialized_data, filter)

        return merged_results

    def _run_query_for_threading(self, result: List, index: int, sql, params):
        result[index] = sync_execute(sql, params)

    def _run_parallel(self, filter: Filter) -> List[Dict[str, Any]]:
        result: List[Union[None, List[Dict[str, Any]]]] = [None] * len(filter.entities)
        parse_functions: List[Union[None, Callable]] = [None] * len(filter.entities)
        jobs = []

        for entity in filter.entities:
            adjusted_filter = self.adjusted_filter(filter)
            sql, params, parse_function = self._get_sql_for_entity(adjusted_filter, entity)
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

    def run(self, *args, **kwargs) -> List[Dict[str, Any]]:
        actions = Action.objects.filter(team_id=self._team.pk).order_by("-id")
        if len(self._filter.actions) > 0:
            actions = Action.objects.filter(
                pk__in=[entity.id for entity in self._filter.actions], team_id=self._team.pk
            )
        actions = actions.prefetch_related(Prefetch("steps", queryset=ActionStep.objects.order_by("id")))

        if self._filter.formula:
            return handle_compare(self._filter, self._run_formula_query, self._team)

        for entity in self._filter.entities:
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                try:
                    entity.name = actions.get(id=entity.id).name
                except Action.DoesNotExist:
                    return []

        if len(self._filter.entities) == 1 or self._filter.compare:
            result = []
            for entity in self._filter.entities:
                result.extend(handle_compare(self._filter, self._run_query, self._team, entity=entity))
        else:
            result = self._run_parallel(self._filter, self._team)

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
