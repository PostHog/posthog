import copy
import threading
from datetime import datetime, timedelta
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

import pytz
from dateutil import parser
from django.db.models.query import Prefetch

from posthog.client import sync_execute
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TRENDS_CUMULATIVE, TRENDS_LIFECYCLE, TRENDS_LINEAR
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
from posthog.utils import generate_cache_key, get_safe_cache
from collections import defaultdict

class Trends(TrendsTotalVolume, Lifecycle, TrendsFormula):
    def _get_sql_for_entity(self, filter: Filter, team: Team, entity: Entity) -> Tuple[str, Dict, Callable]:
        if filter.breakdown:
            sql, params, parse_function = TrendsBreakdown(
                entity, filter, team, using_person_on_events=team.actor_on_events_querying_enabled
            ).get_query()
        elif filter.shown_as == TRENDS_LIFECYCLE:
            sql, params, parse_function = self._format_lifecycle_query(entity, filter, team)
        else:
            sql, params, parse_function = self._total_volume_query(entity, filter, team)

        return sql, params, parse_function

    # Use cached result even on refresh if team has strict caching enabled
    def get_cached_result(self, filter: Filter, team: Team) -> Optional[List[Dict[str, Any]]]:

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
    def is_present_timerange(self, cached_result: List[Dict[str, Any]], filter: Filter, team: Team) -> bool:
        if (
                len(cached_result) > 0
                and cached_result[0].get("days")
                and cached_result[0].get("data")
                and len(cached_result[0]["days"]) > 0
                and len(cached_result[0]["days"]) == len(cached_result[0]["data"])
        ):
            latest_date = cached_result[0]["days"][len(cached_result[0]["days"]) - 1]

            parsed_latest_date = parser.parse(latest_date)
            parsed_latest_date = parsed_latest_date.replace(tzinfo=pytz.timezone(team.timezone))
            _is_present = is_filter_date_present(filter, parsed_latest_date)
        else:
            _is_present = False

        return _is_present

    # Use a condensed filter if a cached result exists in the current timerange
    def adjusted_filter(self, filter: Filter, team: Team) -> Tuple[Filter, Optional[Dict[str, Any]]]:
        cached_result = self.get_cached_result(filter, team)

        new_filter = filter.with_data({"date_from": interval_unit(filter.interval)}) if cached_result else filter

        label_to_payload = {}
        if cached_result:
            for payload in cached_result:
                label_to_payload[f'{payload["label"]}_{payload["action"]["order"]}'] = payload

        return new_filter, label_to_payload

    def merge_results(
            self, result, cached_result: Optional[Dict[str, Any]], entity_order: int, filter: Filter, team: Team
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

    def _run_query(self, filter: Filter, team: Team, entity: Entity) -> List[Dict[str, Any]]:
        adjusted_filter, cached_result = self.adjusted_filter(filter, team)
        sql, params, parse_function = self._get_sql_for_entity(adjusted_filter, team, entity)

        # we run query on each node
        nodes = ["localhost"]
        agg_result = []
        for node in nodes:
            result_each = sync_execute(sql, params)
            agg_result.extend(result_each)

        #xxx
        if filter.breakdown:
            group_with_dup_set = set()
            for result in agg_result:
                group_with_dup_set.add(result[2])
            group = list(group_with_dup_set)
            group.sort()


            result_dict  = defaultdict(lambda:defaultdict(int))
            for breakdown in group:
                for x in agg_result:
                    if(x[2] == breakdown):
                        result_dict[breakdown][x[1]] += x[0]

            final_result_ = []
            for breakdown in group:
                items = list(result_dict[breakdown].items())
                items.sort()
                each_date = [x[0] for x in items]
                each_data = [x[1] for x in items]
                final_result_.append((each_date,each_data,breakdown))

        elif filter.shown_as == TRENDS_LIFECYCLE:
            pass
        else:

            # aggregate each result together
            data = []
            date_with_dup_set = set()
            for result_ in agg_result:
                date_with_dup_set.add(result_[1])
            date = list(date_with_dup_set)
            date.sort()

            for d in date:
                cnt = sum(x[0] for x in [x for x in agg_result if x[1] == d])
                data.append(cnt)

            final_result_ = []
            final_result_.append((date,data))



        final_result = parse_function(final_result_)

        serialized_data = self._format_serialized(entity, final_result)
        merged_results, cached_result = self.merge_results(
            serialized_data, cached_result, entity.order or entity.index, filter, team
        )

        if cached_result:
            for value in cached_result.values():
                merged_results.append(value)

        return merged_results

    def _run_query_for_threading(self, result: List, index: int, sql, params, filter: Filter):
        nodes = ["localhost"]
        agg_result = []
        for node in nodes:
            result_each = sync_execute(sql, params)
            agg_result.extend(result_each)

        # xxx
        if filter.breakdown:

            group_with_dup_set = set()
            for result_ in agg_result:
                group_with_dup_set.add(result_[2])
            group = list(group_with_dup_set)
            group.sort()

            result_dict = defaultdict(lambda: defaultdict(int))
            for breakdown in group:
                for x in agg_result:
                    if (x[2] == breakdown):
                        result_dict[breakdown][x[1]] += x[0]

            final_result_ = []
            for breakdown in group:
                items = list(result_dict[breakdown].items())
                items.sort()
                each_date = [x[0] for x in items]
                each_data = [x[1] for x in items]
                final_result_.append((each_date, each_data, breakdown))


        elif filter.shown_as == TRENDS_LIFECYCLE:
            pass
        else:
            # aggregate each result together
            data = []
            date_with_dup_set = set()
            for result_ in agg_result:
                date_with_dup_set.add(result_[1])
            date = list(date_with_dup_set)
            date.sort()

            for d in date:
                cnt = sum(x[0] for x in [x for x in agg_result if x[1] == d])
                data.append(cnt)

            final_result_ = []
            final_result_.append((date, data))

        result[index] = final_result_




    def _run_parallel(self, filter: Filter, team: Team) -> List[Dict[str, Any]]:
        result: List[Union[None, List[Dict[str, Any]]]] = [None] * len(filter.entities)
        parse_functions: List[Union[None, Callable]] = [None] * len(filter.entities)
        cached_result = None
        jobs = []

        for entity in filter.entities:
            adjusted_filter, cached_result = self.adjusted_filter(filter, team)
            sql, params, parse_function = self._get_sql_for_entity(adjusted_filter, team, entity)
            parse_functions[entity.index] = parse_function
            thread = threading.Thread(target=self._run_query_for_threading, args=(result, entity.index, sql, params, filter), )
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
            merged_results, cached_result = self.merge_results(
                serialized_data, cached_result, entity.order or entity.index, filter, team
            )
            result[entity.index] = merged_results

        # flatten results
        flat_results: List[Dict[str, Any]] = []
        for item in result:
            for flat in cast(List[Dict[str, Any]], item):
                flat_results.append(flat)

            if cached_result:
                for value in cached_result.values():
                    flat_results.append(value)

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
