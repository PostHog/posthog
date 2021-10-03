import copy
import datetime
from itertools import accumulate
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

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
from django.db.models.expressions import ExpressionWrapper, F, RawSQL, Subquery
from django.db.models.fields import DateTimeField
from django.db.models.functions import Cast

from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TRENDS_CUMULATIVE, TRENDS_DISPLAY_BY_VALUE, TRENDS_LIFECYCLE
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
from posthog.utils import append_data, get_daterange

from .base import BaseQuery, filter_events, handle_compare, process_entity_for_events

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


def build_dataarray(
    aggregates: QuerySet, interval: str, breakdown: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], List[Any]]:
    data_array = []
    cohort_dict: Dict[Any, Any] = {}  # keeps data of total count per breakdown
    cohort_keys = []  # contains unique breakdown values
    if breakdown == "cohorts":
        cohort_keys = [key for key in aggregates[0].keys() if key.startswith("cohort_")]
        # Convert queryset with day, count, cohort_88, cohort_99, ... to multiple rows, for example:
        # 2020-01-01..., 1, cohort_88
        # 2020-01-01..., 3, cohort_99
        data_dict: Dict[Any, Any] = {}
        for a in aggregates:
            for key in cohort_keys:
                if a[key]:
                    cohort_dict[key] = cohort_dict.get(key, 0) + a["count"]
                    data_dict[(a[interval], key)] = data_dict.get((a[interval], key), 0) + a["count"]

        data_array = [{"date": key[0], "count": value, "breakdown": key[1]} for key, value in data_dict.items()]

    else:
        for a in aggregates:
            key = a[breakdown] if breakdown else "Total"
            cohort_keys.append(key)
            cohort_dict[key] = cohort_dict.get(key, 0) + a["count"]
            data_array.append(
                {"date": a[interval], "count": a["count"], "breakdown": key,}
            )
        cohort_keys = list(dict.fromkeys(cohort_keys))  # getting unique breakdowns keeping their order

    # following finds top 25 breakdown in given queryset then removes other rows from data array
    # only 20 will be returned in the payload but we find extra keys for paginating purposes
    if len(cohort_keys) > 20:
        top25keys = [x[0] for x in sorted(cohort_dict.items(), key=lambda x: -x[1])[:25]]
        cohort_keys = [key for key in top25keys if key in cohort_keys]
        data_array = list(filter(lambda d: d["breakdown"] in cohort_keys, data_array))

    if interval == "week":
        for df in data_array:
            df["date"] -= datetime.timedelta(days=df["date"].weekday() + 1)
    return data_array, list(dict.fromkeys(cohort_keys))


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

    time_index = get_daterange(date_from, date_to, frequency=interval)
    if len(aggregates) > 0:
        dataframe, unique_cohorts = build_dataarray(aggregates, interval, breakdown)

        for value in unique_cohorts:
            filtered = list(filter(lambda d: d["breakdown"] == value, dataframe))
            datewise_data = {d["date"]: d["count"] for d in filtered}
            if value is None:
                value = "nan"
            response[value] = {key: datewise_data.get(key, 0) for key in time_index}
    else:
        response["total"] = {key: 0 for key in time_index}

    return response


def get_interval_annotation(key: str) -> Dict[str, Any]:
    map: Dict[str, Any] = {
        "minute": functions.TruncMinute("timestamp"),
        "hour": functions.TruncHour("timestamp"),
        "day": functions.TruncDay("timestamp"),
        "week": functions.TruncWeek(
            ExpressionWrapper(F("timestamp") + datetime.timedelta(days=1), output_field=DateTimeField())
        ),
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
        annotations[f"cohort_{cohort.pk}"] = Exists(
            CohortPeople.objects.filter(cohort=cohort.pk, person_id=OuterRef("person_id")).only("id")
        )
    if "all" in breakdown:
        annotations["cohort_all"] = Value(True, output_field=BooleanField())
    return annotations


def add_person_properties_annotations(team_id: int, breakdown: str) -> Dict[str, Subquery]:
    person_properties = Subquery(
        Person.objects.filter(team_id=team_id, id=OuterRef("person_id")).values(f"properties__{breakdown}")
    )
    annotations = {}
    annotations[f"properties__{breakdown}"] = person_properties
    return annotations


def aggregate_by_interval(
    events: QuerySet, team_id: int, entity: Entity, filter: Filter, breakdown: Optional[str] = None,
) -> Tuple[Dict[str, Any], QuerySet]:
    interval = filter.interval
    interval_annotation = get_interval_annotation(interval)
    filtered_events = events.filter(
        filter_events(team_id, filter, entity, interval_annotation=interval_annotation[interval])
    )
    values: List[str] = [interval]
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

    aggregates = process_math(aggregates, entity)

    dates_filled = group_events_to_date(
        date_from=filter.date_from,
        date_to=filter.date_to,
        aggregates=aggregates,
        interval=interval,
        breakdown=breakdown,
    )

    return dates_filled, filtered_events


def get_aggregate_total(query: QuerySet, entity: Entity) -> int:
    entity_total = 0
    if entity.math == "dau":
        _query, _params = query.query.sql_with_params()
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT count(DISTINCT person_id) FROM ({_query}) as aggregates", _params)
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
            cursor.execute(f"SELECT {agg_func} FROM ({_query}) as aggregates", (_params))
            entity_total = cursor.fetchall()[0][0]
    else:
        entity_total = len(query)
    return entity_total


def get_aggregate_breakdown_total(
    filtered_events: QuerySet, filter: Filter, entity: Entity, team_id: int, breakdown_value: Union[str, int]
) -> int:
    if len(filtered_events) == 0:
        return 0

    breakdown_filter: Dict[str, Union[bool, str, int]] = {}
    if filter.breakdown_type == "cohort":
        breakdown_filter = {f"cohort_{breakdown_value}": True}
    else:
        breakdown_filter = {f"properties__{filter.breakdown}": breakdown_value}
    filtered_events = filtered_events.filter(**breakdown_filter)

    return get_aggregate_total(filtered_events, entity)


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
        label = value if (value or type(value) == bool) and value != "None" and value != "nan" else "Other"
        ret_dict["label"] = f"{entity.name} - {label}"
        ret_dict["breakdown_value"] = label
    else:
        if value == "cohort_all":
            ret_dict["label"] = f"{entity.name} - all users"
            ret_dict["breakdown_value"] = "all"
        else:
            cohort = Cohort.objects.get(pk=value.replace("cohort_", ""))
            ret_dict["label"] = f"{entity.name} - {cohort.name}"
            ret_dict["breakdown_value"] = cohort.pk
    return ret_dict


class Trends(LifecycleTrend, BaseQuery):
    def _serialize_entity(self, entity: Entity, filter: Filter, team_id: int) -> List[Dict[str, Any]]:

        if filter.breakdown:
            result = self._serialize_breakdown(entity, filter, team_id)
        elif filter.shown_as == TRENDS_LIFECYCLE:
            result = self._serialize_lifecycle(entity, filter, team_id)
        else:
            result = self._format_total_volume_query(entity, filter, team_id)

        serialized_data = self._format_serialized(entity, result)

        if filter.display == TRENDS_CUMULATIVE:
            serialized_data = self._handle_cumulative(serialized_data)

        return serialized_data

    def _set_default_dates(self, filter: Filter, team_id: int) -> Filter:
        # format default dates
        if not filter.date_from:
            return Filter(
                data={
                    **filter._data,
                    "date_from": Event.objects.filter(team_id=team_id)
                    .order_by("timestamp")[0]
                    .timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
                    .isoformat(),
                }
            )
        return filter

    def _format_total_volume_query(self, entity: Entity, filter: Filter, team_id: int) -> List[Dict[str, Any]]:
        events = process_entity_for_events(entity=entity, team_id=team_id, order_by="-timestamp",)

        items, filtered_events = aggregate_by_interval(events=events, team_id=team_id, entity=entity, filter=filter,)
        formatted_entities: List[Dict[str, Any]] = []
        for _, item in items.items():
            formatted_data = append_data(dates_filled=list(item.items()), interval=filter.interval)
            if filter.display in TRENDS_DISPLAY_BY_VALUE:
                formatted_data.update({"aggregated_value": get_aggregate_total(filtered_events, entity)})
            formatted_entities.append(formatted_data)
        return formatted_entities

    def _serialize_breakdown(self, entity: Entity, filter: Filter, team_id: int) -> List[Dict[str, Any]]:
        events = process_entity_for_events(entity=entity, team_id=team_id, order_by="-timestamp",)
        items, filtered_events = aggregate_by_interval(
            events=events,
            team_id=team_id,
            entity=entity,
            filter=filter,
            breakdown=f"properties__{filter.breakdown}" if filter.breakdown else None,
        )
        formatted_entities: List[Dict[str, Any]] = []
        for value, item in items.items():
            new_dict = append_data(dates_filled=list(item.items()), interval=filter.interval)
            if value != "Total":
                new_dict.update(breakdown_label(entity, value))
            if filter.display in TRENDS_DISPLAY_BY_VALUE:
                new_dict.update(
                    {
                        "aggregated_value": get_aggregate_breakdown_total(
                            filtered_events, filter, entity, team_id, new_dict["breakdown_value"]
                        )
                    }
                )
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

        filter = self._set_default_dates(filter, team.pk)

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
