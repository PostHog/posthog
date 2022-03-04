import copy
import threading
from itertools import accumulate
from typing import Any, Callable, Dict, List, Tuple

from django.db.models.query import Prefetch
from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.queries.trends.breakdown import ClickhouseTrendsBreakdown
from ee.clickhouse.queries.trends.formula import ClickhouseTrendsFormula
from ee.clickhouse.queries.trends.lifecycle import ClickhouseLifecycle
from ee.clickhouse.queries.trends.total_volume import ClickhouseTrendsTotalVolume
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TRENDS_CUMULATIVE, TRENDS_LIFECYCLE
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.team import Team
from posthog.queries.base import handle_compare, handle_compare_threading
from posthog.utils import relative_date_parse


class ClickhouseTrends(ClickhouseTrendsTotalVolume, ClickhouseLifecycle, ClickhouseTrendsFormula):
    def _set_default_dates(self, filter: Filter, team_id: int) -> Filter:
        data = {}
        if not filter._date_from:
            data.update({"date_from": relative_date_parse("-7d")})
        if not filter._date_to:
            data.update({"date_to": timezone.now()})
        if data:
            return Filter(data={**filter._data, **data})
        return filter

    def _get_sql_for_entity(self, filter: Filter, entity: Entity, team_id: int) -> Tuple[str, Dict, Callable]:
        if filter.breakdown:
            sql, params, parse_function = ClickhouseTrendsBreakdown(entity, filter, team_id).get_query()
        elif filter.shown_as == TRENDS_LIFECYCLE:
            sql, params, parse_function = self._format_lifecycle_query(entity, filter, team_id)
        else:
            sql, params, parse_function = self._total_volume_query(entity, filter, team_id)

        return sql, params, parse_function

    def _run_query(self, filter: Filter, entity: Entity, team_id: int) -> List[Dict[str, Any]]:
        sql, params, parse_function = self._get_sql_for_entity(filter, entity, team_id)
        result = sync_execute(sql, params)

        result = parse_function(result)
        serialized_data = self._format_serialized(entity, result)

        if filter.display == TRENDS_CUMULATIVE:
            serialized_data = self._handle_cumulative(serialized_data)
        return serialized_data

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        actions = Action.objects.filter(team_id=team.pk).order_by("-id")
        if len(filter.actions) > 0:
            actions = Action.objects.filter(pk__in=[entity.id for entity in filter.actions], team_id=team.pk)
        actions = actions.prefetch_related(Prefetch("steps", queryset=ActionStep.objects.order_by("id")))

        filter = self._set_default_dates(filter, team.pk)

        if filter.formula:
            return handle_compare(filter, self._run_formula_query, team)

        jobs = []
        result = [None] * len(filter.entities)
        for entity in filter.entities:
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                try:
                    entity.name = actions.get(id=entity.id).name
                except Action.DoesNotExist:
                    continue
            thread = threading.Thread(
                target=handle_compare_threading,
                args=(filter, self._run_query, team),
                kwargs={"entity": entity, "result": result, "index": entity.index},
            )
            jobs.append(thread)

        # Start the threads (i.e. calculate the random number lists)
        for j in jobs:
            j.start()

        # Ensure all of the threads have finished
        for j in jobs:
            j.join()

        # flatten results
        return [item for sublist in result for item in sublist]

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
