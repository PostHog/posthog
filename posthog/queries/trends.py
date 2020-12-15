import copy
import datetime
from itertools import accumulate
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from django.db import connection
from django.db.models import (
    Avg,
    BooleanField,
    Count,
    Exists,
    FloatField,
    Max,
    Min,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Sum,
    Value,
    functions,
)
from django.db.models.expressions import F, RawSQL, Subquery
from django.db.models.functions import Cast
from django.db.models.functions.datetime import TruncDay, TruncHour, TruncMonth, TruncWeek

from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS, TRENDS_CUMULATIVE, TRENDS_LIFECYCLE
from posthog.models import (
    Action,
    ActionStep,
    Cohort,
    CohortPeople,
    Entity,
    Event,
    Filter,
    Person,
    Team,
)
from posthog.models.utils import Percentile
from posthog.queries.lifecycle import LifecycleTrend
from posthog.utils import append_data

from .base import BaseQuery, filter_events, handle_compare, process_entity_for_events

FREQ_MAP = {"minute": "60S", "hour": "H", "day": "D", "week": "W", "month": "M"}

MATH_TO_AGGREGATE_FUNCTION: Dict[str, Callable] = {
    "sum": Sum,
    "avg": Avg,
    "min": Min,
    "max": Max,
    "median": lambda expr: Percentile(0.5, expr),
    "p90": lambda expr: Percentile(0.9, expr),
    "p95": lambda expr: Percentile(0.95, expr),
    "p99": lambda expr: Percentile(0.99, expr),
}

MATH_TO_AGGREGATE_STRING: Dict[str, str] = {
    "sum": "SUM({math_prop})",
    "avg": "AVG({math_prop})",
    "min": "MIN({math_prop})",
    "max": "MAX({math_prop})",
    "median": "percentile_disc(0.5) WITHIN GROUP (ORDER BY {math_prop})",
    "p90": "percentile_disc(0.9) WITHIN GROUP (ORDER BY {math_prop})",
    "p95": "percentile_disc(0.95) WITHIN GROUP (ORDER BY {math_prop})",
    "p99": "percentile_disc(0.99) WITHIN GROUP (ORDER BY {math_prop})",
}


def build_dataframe(aggregates: QuerySet, interval: str, breakdown: Optional[str] = None) -> pd.DataFrame:
    if breakdown == "cohorts":
        cohort_keys = [key for key in aggregates[0].keys() if key.startswith("cohort_")]
        # Convert queryset with day, count, cohort_88, cohort_99, ... to multiple rows, for example:
        # 2020-01-01..., 1, cohort_88
        # 2020-01-01..., 3, cohort_99
        dataframe = pd.melt(
            pd.DataFrame(aggregates), id_vars=[interval, "count"], value_vars=cohort_keys, var_name="breakdown",
        ).rename(columns={interval: "date"})
        # Filter out false values
        dataframe = dataframe[dataframe["value"] == True]
        # Sum dates with same cohort
        dataframe = dataframe.groupby(["breakdown", "date"], as_index=False).sum()
    else:
        dataframe = pd.DataFrame(
            [
                {"date": a[interval], "count": a["count"], "breakdown": a[breakdown] if breakdown else "Total",}
                for a in aggregates
            ]
        )
    if interval == "week":
        dataframe["date"] = dataframe["date"].apply(lambda x: x - pd.offsets.Week(weekday=6))
    elif interval == "month":
        dataframe["date"] = dataframe["date"].apply(lambda x: x - pd.offsets.MonthEnd(n=1))
    return dataframe


def group_events_to_date(
    date_from: Optional[datetime.datetime],
    date_to: Optional[datetime.datetime],
    aggregates: QuerySet,
    interval: str,
    breakdown: Optional[str] = None,
) -> Dict[str, Dict[datetime.datetime, int]]:
    response = {}

    if interval == "day":
        if date_from:
            date_from = date_from.replace(hour=0, minute=0, second=0, microsecond=0)
        if date_to:
            date_to = date_to.replace(hour=0, minute=0, second=0, microsecond=0)

    time_index = pd.date_range(date_from, date_to, freq=FREQ_MAP[interval])
    if len(aggregates) > 0:
        dataframe = build_dataframe(aggregates, interval, breakdown)

        # extract top 20 if more than 20 breakdowns
        if breakdown and dataframe["breakdown"].nunique() > 20:
            counts = (
                dataframe.groupby(["breakdown"])["count"]
                .sum()
                .reset_index(name="total")
                .sort_values(by=["total"], ascending=False)[:20]
            )
            top_breakdown = counts["breakdown"].to_list()
            dataframe = dataframe[dataframe.breakdown.isin(top_breakdown)]
        dataframe = dataframe.astype({"breakdown": str})
        for value in dataframe["breakdown"].unique():
            filtered = (
                dataframe.loc[dataframe["breakdown"] == value]
                if value
                else dataframe.loc[dataframe["breakdown"].isnull()]
            )
            df_dates = pd.DataFrame(filtered.groupby("date").mean(), index=time_index)
            df_dates = df_dates.fillna(0)
            response[value] = {key: value[0] if len(value) > 0 else 0 for key, value in df_dates.iterrows()}
    else:
        dataframe = pd.DataFrame([], index=time_index)
        dataframe = dataframe.fillna(0)
        response["total"] = {key: value[0] if len(value) > 0 else 0 for key, value in dataframe.iterrows()}

    return response


def get_interval_annotation(key: str) -> Dict[str, Any]:
    map: Dict[str, Any] = {
        "minute": functions.TruncMinute("timestamp"),
        "hour": functions.TruncHour("timestamp"),
        "day": functions.TruncDay("timestamp"),
        "week": functions.TruncWeek("timestamp"),
        "month": functions.TruncMonth("timestamp"),
    }
    func = map.get(key)
    if func is None:
        return {"day": map.get("day")}  # default

    return {key: func}


def add_cohort_annotations(team_id: int, breakdown: List[Union[int, str]]) -> Dict[str, Union[Value, Exists]]:
    cohorts = Cohort.objects.filter(team_id=team_id, pk__in=[b for b in breakdown if b != "all"])
    annotations: Dict[str, Union[Value, Exists]] = {}
    for cohort in cohorts:
        annotations["cohort_{}".format(cohort.pk)] = Exists(
            CohortPeople.objects.filter(cohort=cohort.pk, person_id=OuterRef("person_id")).only("id")
        )
    if "all" in breakdown:
        annotations["cohort_all"] = Value(True, output_field=BooleanField())
    return annotations


def add_person_properties_annotations(team_id: int, breakdown: str) -> Dict[str, Subquery]:
    person_properties = Subquery(
        Person.objects.filter(team_id=team_id, id=OuterRef("person_id")).values("properties__{}".format(breakdown))
    )
    annotations = {}
    annotations["properties__{}".format(breakdown)] = person_properties
    return annotations


def aggregate_by_interval(
    filtered_events: QuerySet, team_id: int, entity: Entity, filter: Filter, breakdown: Optional[str] = None,
) -> Tuple[Dict[str, Any], int]:
    interval = filter.interval if filter.interval else "day"
    interval_annotation = get_interval_annotation(interval)
    values = [interval]
    if breakdown:
        if filter.breakdown_type == "cohort":
            cohort_annotations = add_cohort_annotations(
                team_id, filter.breakdown if filter.breakdown and isinstance(filter.breakdown, list) else []
            )
            values.extend(cohort_annotations.keys())
            filtered_events = filtered_events.annotate(**cohort_annotations)
            breakdown = "cohorts"
        elif filter.breakdown_type == "person":
            person_annotations = add_person_properties_annotations(
                team_id, filter.breakdown if filter.breakdown and isinstance(filter.breakdown, str) else ""
            )
            filtered_events = filtered_events.annotate(**person_annotations)
            values.append(breakdown)
        else:
            values.append(breakdown)
    aggregates = filtered_events.annotate(**interval_annotation).values(*values).annotate(count=Count(1)).order_by()

    if breakdown:
        aggregates = aggregates.order_by("-count")

    entity_total = get_aggregate_total(filtered_events, entity)
    aggregates = process_math(aggregates, entity)

    dates_filled = group_events_to_date(
        date_from=filter.date_from,
        date_to=filter.date_to,
        aggregates=aggregates,
        interval=interval,
        breakdown=breakdown,
    )

    return dates_filled, entity_total


def get_aggregate_total(query: QuerySet, entity: Entity) -> int:
    entity_total = 0
    if entity.math == "dau":
        _query, _params = query.query.sql_with_params()
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(DISTINCT person_id) FROM ({}) as aggregates".format(_query), _params)
            entity_total = cursor.fetchall()[0][0]
    elif entity.math in MATH_TO_AGGREGATE_FUNCTION:
        query = query.annotate(
            math_prop=Cast(
                RawSQL('"posthog_event"."properties"->>%s', (entity.math_property,)), output_field=FloatField(),
            )
        )
        query = query.extra(
            where=['jsonb_typeof("posthog_event"."properties"->%s) = \'number\''], params=[entity.math_property],
        )
        _query, _params = query.query.sql_with_params()
        with connection.cursor() as cursor:
            agg_func = MATH_TO_AGGREGATE_STRING[entity.math].format(math_prop="math_prop")
            cursor.execute("SELECT {} FROM ({}) as aggregates".format(agg_func, _query), (_params))
            entity_total = cursor.fetchall()[0][0]
    else:
        entity_total = len(query)
    return entity_total


def process_math(query: QuerySet, entity: Entity) -> QuerySet:
    if entity.math == "dau":
        # In daily active users mode count only up to 1 event per user per day
        query = query.annotate(count=Count("person_id", distinct=True))
    elif entity.math in MATH_TO_AGGREGATE_FUNCTION:
        # Run relevant aggregate function on specified event property, casting it to a double
        query = query.annotate(
            count=MATH_TO_AGGREGATE_FUNCTION[entity.math](
                Cast(RawSQL('"posthog_event"."properties"->>%s', (entity.math_property,)), output_field=FloatField(),)
            )
        )
        # Skip over events where the specified property is not set or not a number
        # It may not be ideally clear to the user what events were skipped,
        # but in the absence of typing, this is safe, cheap, and frictionless
        query = query.extra(
            where=['jsonb_typeof("posthog_event"."properties"->%s) = \'number\''], params=[entity.math_property],
        )
    return query


def breakdown_label(entity: Entity, value: Union[str, int]) -> Dict[str, Optional[Union[str, int]]]:
    ret_dict: Dict[str, Optional[Union[str, int]]] = {}
    if not value or not isinstance(value, str) or "cohort_" not in value:
        ret_dict["label"] = "{} - {}".format(
            entity.name, value if value and value != "None" and value != "nan" else "Other",
        )
        ret_dict["breakdown_value"] = value if value and not pd.isna(value) else None
    else:
        if value == "cohort_all":
            ret_dict["label"] = "{} - all users".format(entity.name)
            ret_dict["breakdown_value"] = "all"
        else:
            cohort = Cohort.objects.get(pk=value.replace("cohort_", ""))
            ret_dict["label"] = "{} - {}".format(entity.name, cohort.name)
            ret_dict["breakdown_value"] = cohort.pk
    return ret_dict


class Trends(LifecycleTrend, BaseQuery):
    def _serialize_entity(self, entity: Entity, filter: Filter, team_id: int) -> List[Dict[str, Any]]:

        if filter.breakdown:
            result = self._serialize_breakdown(entity, filter, team_id)
        elif filter.shown_as == TRENDS_LIFECYCLE:
            result = self._serialize_lifecycle(entity, filter, team_id)
        else:
            result = self._format_normal_query(entity, filter, team_id)

        serialized_data = self._format_serialized(entity, result)

        if filter.display == TRENDS_CUMULATIVE:
            serialized_data = self._handle_cumulative(serialized_data)

        return serialized_data

    def _set_default_dates(self, filter: Filter, team_id: int) -> None:
        # format default dates
        if not filter.date_from:
            filter._date_from = (
                Event.objects.filter(team_id=team_id)
                .order_by("timestamp")[0]
                .timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
                .isoformat()
            )

    def _format_normal_query(self, entity: Entity, filter: Filter, team_id: int) -> List[Dict[str, Any]]:
        events = process_entity_for_events(entity=entity, team_id=team_id, order_by="-timestamp",)
        events = events.filter(filter_events(team_id, filter, entity))
        items, entity_total = aggregate_by_interval(
            filtered_events=events, team_id=team_id, entity=entity, filter=filter,
        )
        formatted_entities: List[Dict[str, Any]] = []
        for _, item in items.items():
            formatted_data = append_data(dates_filled=list(item.items()), interval=filter.interval)
            formatted_data.update({"aggregated_value": entity_total})
            formatted_entities.append(formatted_data)
        return formatted_entities

    def _serialize_breakdown(self, entity: Entity, filter: Filter, team_id: int) -> List[Dict[str, Any]]:
        events = process_entity_for_events(entity=entity, team_id=team_id, order_by="-timestamp",)
        events = events.filter(filter_events(team_id, filter, entity))
        items, entity_total = aggregate_by_interval(
            filtered_events=events,
            team_id=team_id,
            entity=entity,
            filter=filter,
            breakdown="properties__{}".format(filter.breakdown) if filter.breakdown else None,
        )
        formatted_entities: List[Dict[str, Any]] = []
        for value, item in items.items():
            new_dict = append_data(dates_filled=list(item.items()), interval=filter.interval)
            new_dict.update({"aggregated_value": entity_total})
            if value != "Total":
                new_dict.update(breakdown_label(entity, value))
            formatted_entities.append(new_dict)
        return formatted_entities

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

    def calculate_trends(self, filter: Filter, team: Team) -> List[Dict[str, Any]]:
        actions = Action.objects.filter(team_id=team.pk).order_by("-id")
        if len(filter.actions) > 0:
            actions = Action.objects.filter(pk__in=[entity.id for entity in filter.actions], team_id=team.pk)
        actions = actions.prefetch_related(Prefetch("steps", queryset=ActionStep.objects.order_by("id")))

        self._set_default_dates(filter, team.pk)

        result = []
        for entity in filter.entities:
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                try:
                    entity.name = actions.get(id=entity.id).name
                except Action.DoesNotExist:
                    continue
            entities_list = handle_compare(filter, self._serialize_entity, team, entity=entity)
            result.extend(entities_list)

        return result

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        return self.calculate_trends(filter, team)
