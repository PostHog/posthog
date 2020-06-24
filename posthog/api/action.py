from django.db.models.expressions import Subquery
from posthog.models import person
from posthog.models import (
    Event,
    Team,
    Action,
    ActionStep,
    DashboardItem,
    User,
    Person,
    Filter,
    Entity,
    Cohort,
    CohortPeople,
)
from posthog.utils import (
    append_data,
    get_compare_period_dates,
    TemporaryTokenAuthentication,
)
from posthog.constants import (
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
    TRENDS_CUMULATIVE,
    TRENDS_STICKINESS,
)
from posthog.tasks.calculate_action import calculate_action
from rest_framework import request, serializers, viewsets, authentication
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import (
    Q,
    Count,
    Prefetch,
    functions,
    QuerySet,
    OuterRef,
    Exists,
    Value,
    BooleanField,
)
from django.db import connection
from django.utils.timezone import now
from typing import Any, List, Dict, Optional, Tuple, Union
import pandas as pd
import datetime
import json
import pytz
import copy
import numpy as np
from dateutil.relativedelta import relativedelta
import dateutil
from .person import PersonSerializer
from urllib.parse import urlsplit
from django.core.cache import cache
from posthog.decorators import cached_function, TRENDS_ENDPOINT

FREQ_MAP = {"minute": "60S", "hour": "H", "day": "D", "week": "W", "month": "M"}


class ActionStepSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = ActionStep
        fields = [
            "id",
            "event",
            "tag_name",
            "text",
            "href",
            "selector",
            "url",
            "name",
            "url_matching",
            "properties",
        ]


class ActionSerializer(serializers.HyperlinkedModelSerializer):
    steps = serializers.SerializerMethodField()
    count = serializers.SerializerMethodField()

    class Meta:
        model = Action
        fields = [
            "id",
            "name",
            "post_to_slack",
            "steps",
            "created_at",
            "deleted",
            "count",
            "is_calculating",
        ]

    def get_steps(self, action: Action):
        steps = action.steps.all()
        return ActionStepSerializer(steps, many=True).data

    def get_count(self, action: Action) -> Optional[int]:
        if hasattr(action, "count"):
            return action.count  # type: ignore
        return None


def get_actions(queryset: QuerySet, params: dict, team_id: int) -> QuerySet:
    if params.get(TREND_FILTER_TYPE_ACTIONS):
        queryset = queryset.filter(
            pk__in=[
                action.id
                for action in Filter(
                    {"actions": json.loads(params.get("actions", "[]"))}
                ).actions
            ]
        )

    if params.get("include_count"):
        queryset = queryset.annotate(count=Count(TREND_FILTER_TYPE_EVENTS))

    queryset = queryset.prefetch_related(
        Prefetch("steps", queryset=ActionStep.objects.order_by("id"))
    )
    return queryset.filter(team_id=team_id).order_by("-id")


class ActionViewSet(viewsets.ModelViewSet):
    queryset = Action.objects.all()
    serializer_class = ActionSerializer
    authentication_classes = [
        TemporaryTokenAuthentication,
        authentication.SessionAuthentication,
        authentication.BasicAuthentication,
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "list":  # type: ignore
            queryset = queryset.filter(deleted=False)
        return get_actions(
            queryset, self.request.GET.dict(), self.request.user.team_set.get().pk
        )

    def create(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        action, created = Action.objects.get_or_create(
            name=request.data["name"],
            team=request.user.team_set.get(),
            deleted=False,
            defaults={
                "post_to_slack": request.data.get("post_to_slack", False),
                "created_by": request.user,
            },
        )
        if not created:
            return Response(
                data={"detail": "action-exists", "id": action.pk}, status=400
            )

        if request.data.get("steps"):
            for step in request.data["steps"]:
                ActionStep.objects.create(
                    action=action,
                    **{
                        key: value
                        for key, value in step.items()
                        if key not in ("isNew", "selection")
                    }
                )
        calculate_action.delay(action_id=action.pk)
        return Response(ActionSerializer(action, context={"request": request}).data)

    def update(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        action = Action.objects.get(pk=kwargs["pk"], team=request.user.team_set.get())

        # If there's no steps property at all we just ignore it
        # If there is a step property but it's an empty array [], we'll delete all the steps
        if "steps" in request.data:
            steps = request.data.pop("steps")
            # remove steps not in the request
            step_ids = [step["id"] for step in steps if step.get("id")]
            action.steps.exclude(pk__in=step_ids).delete()

            for step in steps:
                if step.get("id"):
                    db_step = ActionStep.objects.get(pk=step["id"])
                    step_serializer = ActionStepSerializer(db_step)
                    step_serializer.update(db_step, step)
                else:
                    ActionStep.objects.create(
                        action=action,
                        **{
                            key: value
                            for key, value in step.items()
                            if key not in ("isNew", "selection")
                        }
                    )

        serializer = ActionSerializer(action, context={"request": request})
        serializer.update(action, request.data)
        action.is_calculating = True
        calculate_action.delay(action_id=action.pk)
        return Response(ActionSerializer(action, context={"request": request}).data)

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        actions = self.get_queryset()
        actions_list: List[Dict[Any, Any]] = ActionSerializer(actions, many=True, context={"request": request}).data  # type: ignore
        if request.GET.get("include_count", False):
            actions_list.sort(
                key=lambda action: action.get("count", action["id"]), reverse=True
            )
        return Response({"results": actions_list})

    @action(methods=["GET"], detail=False)
    def trends(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        result = self._calculate_trends(request)
        return Response(result)

    @cached_function(cache_type=TRENDS_ENDPOINT)
    def _calculate_trends(self, request: request.Request) -> List[Dict[str, Any]]:
        team = request.user.team_set.get()
        actions = self.get_queryset()
        params = request.GET.dict()
        filter = Filter(request=request)
        result = calculate_trends(filter, params, team.pk, actions)

        dashboard_id = request.GET.get("from_dashboard", None)
        if dashboard_id:
            DashboardItem.objects.filter(pk=dashboard_id).update(
                last_refresh=datetime.datetime.now()
            )

        return result

    @action(methods=["GET"], detail=False)
    def people(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        team = request.user.team_set.get()
        filter = Filter(request=request)
        offset = int(request.GET.get("offset", 0))

        def _calculate_people(events: QuerySet, offset: int):
            shown_as = request.GET.get("shown_as")
            if shown_as is not None and shown_as == "Stickiness":
                stickiness_days = int(request.GET["stickiness_days"])
                events = (
                    events.values("person_id")
                    .annotate(
                        day_count=Count(functions.TruncDay("timestamp"), distinct=True)
                    )
                    .filter(day_count=stickiness_days)
                )
            else:
                events = events.values("person_id").distinct()

            if (
                request.GET.get("breakdown_type") == "cohort"
                and request.GET.get("breakdown_value") != "all"
            ):
                events = events.filter(
                    Exists(
                        CohortPeople.objects.filter(
                            cohort_id=int(request.GET["breakdown_value"]),
                            person_id=OuterRef("person_id"),
                        ).only("id")
                    )
                )
            if request.GET.get("breakdown_type") == "person":
                events = events.filter(
                    Exists(
                        Person.objects.filter(
                            **{
                                "id": OuterRef("person_id"),
                                "properties__{}".format(
                                    request.GET["breakdown"]
                                ): request.GET["breakdown_value"],
                            }
                        ).only("id")
                    )
                )

            people = Person.objects.filter(
                team=team,
                id__in=[p["person_id"] for p in events[offset : offset + 100]],
            )

            people = people.prefetch_related(
                Prefetch("persondistinctid_set", to_attr="distinct_ids_cache")
            )

            return serialize_people(people=people, request=request)

        filtered_events: QuerySet = QuerySet()
        if request.GET.get("session"):
            filtered_events = (
                Event.objects.filter(team=team)
                .filter(filter_events(team.pk, filter))
                .add_person_id(team.pk)
            )
        else:
            if len(filter.entities) >= 1:
                entity = filter.entities[0]
            else:
                entity = Entity(
                    {"id": request.GET["entityId"], "type": request.GET["type"]}
                )

            if entity.type == TREND_FILTER_TYPE_EVENTS:
                filtered_events = process_entity_for_events(
                    entity, team_id=team.pk, order_by=None
                ).filter(filter_events(team.pk, filter, entity))
            elif entity.type == TREND_FILTER_TYPE_ACTIONS:
                actions = super().get_queryset()
                actions = actions.filter(deleted=False)
                try:
                    action = actions.get(pk=entity.id)
                except Action.DoesNotExist:
                    return Response([])
                filtered_events = process_entity_for_events(
                    entity, team_id=team.pk, order_by=None
                ).filter(filter_events(team.pk, filter, entity))

        people = _calculate_people(events=filtered_events, offset=offset)

        current_url = request.get_full_path()
        next_url: Optional[str] = request.get_full_path()
        if people["count"] > 99 and next_url:
            if "offset" in next_url:
                next_url = next_url[1:]
                next_url = next_url.replace(
                    "offset=" + str(offset), "offset=" + str(offset + 100)
                )
            else:
                next_url = request.build_absolute_uri(
                    "{}{}offset={}".format(
                        next_url, "&" if "?" in next_url else "?", offset + 100
                    )
                )
        else:
            next_url = None

        return Response(
            {"results": [people], "next": next_url, "previous": current_url[1:]}
        )


def calculate_trends(
    filter: Filter, params: dict, team_id: int, actions: QuerySet
) -> List[Dict[str, Any]]:
    compare = params.get("compare")
    entities_list = []
    actions = actions.filter(deleted=False)

    if len(filter.entities) == 0:
        # If no filters, automatically grab all actions and show those instead
        filter.entities = [
            Entity(
                {
                    "id": action.id,
                    "name": action.name,
                    "type": TREND_FILTER_TYPE_ACTIONS,
                }
            )
            for action in actions
        ]

    if not filter.date_from:
        filter._date_from = (
            Event.objects.filter(team_id=team_id)
            .order_by("timestamp")[0]
            .timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
    if not filter.date_to:
        filter._date_to = now().isoformat()

    compared_filter = None
    if compare:
        compared_filter = determine_compared_filter(filter)

    for entity in filter.entities:
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            try:
                db_action = [action for action in actions if action.id == entity.id][0]
                entity.name = db_action.name
            except IndexError:
                continue
        trend_entity = serialize_entity(
            entity=entity, filter=filter, params=params, team_id=team_id
        )
        if compare and compared_filter:
            trend_entity = convert_to_comparison(
                trend_entity, filter, "{} - {}".format(entity.name, "current")
            )
            entities_list.extend(trend_entity)

            compared_trend_entity = serialize_entity(
                entity=entity, filter=compared_filter, params=params, team_id=team_id
            )

            compared_trend_entity = convert_to_comparison(
                compared_trend_entity,
                compared_filter,
                "{} - {}".format(entity.name, "previous"),
            )
            entities_list.extend(compared_trend_entity)
        else:
            entities_list.extend(trend_entity)
    return entities_list


def build_dataframe(
    aggregates: QuerySet, interval: str, breakdown: Optional[str] = None
) -> pd.DataFrame:
    if breakdown == "cohorts":
        cohort_keys = [key for key in aggregates[0].keys() if key.startswith("cohort_")]
        # Convert queryset with day, count, cohort_88, cohort_99, ... to multiple rows, for example:
        # 2020-01-01..., 1, cohort_88
        # 2020-01-01..., 3, cohort_99
        dataframe = pd.melt(
            pd.DataFrame(aggregates),
            id_vars=[interval, "count"],
            value_vars=cohort_keys,
            var_name="breakdown",
        ).rename(columns={interval: "date"})
        # Filter out false values
        dataframe = dataframe[dataframe["value"] == True]
        # Sum dates with same cohort
        dataframe = dataframe.groupby(["breakdown", "date"], as_index=False).sum()
    else:
        dataframe = pd.DataFrame(
            [
                {
                    "date": a[interval],
                    "count": a["count"],
                    "breakdown": a[breakdown] if breakdown else "Total",
                }
                for a in aggregates
            ]
        )
    if interval == "week":
        dataframe["date"] = dataframe["date"].apply(
            lambda x: x - pd.offsets.Week(weekday=6)
        )
    elif interval == "month":
        dataframe["date"] = dataframe["date"].apply(
            lambda x: x - pd.offsets.MonthEnd(n=1)
        )
    return dataframe


def group_events_to_date(
    date_from: Optional[datetime.datetime],
    date_to: Optional[datetime.datetime],
    aggregates: QuerySet,
    interval: str,
    breakdown: Optional[str] = None,
) -> Dict[str, Dict[datetime.datetime, int]]:
    response = {}

    time_index = pd.date_range(date_from, date_to, freq=FREQ_MAP[interval])
    if len(aggregates) > 0:
        dataframe = build_dataframe(aggregates, interval, breakdown)
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
            response[value] = {
                key: value[0] if len(value) > 0 else 0
                for key, value in df_dates.iterrows()
            }
    else:
        dataframe = pd.DataFrame([], index=time_index)
        dataframe = dataframe.fillna(0)
        response["total"] = {
            key: value[0] if len(value) > 0 else 0
            for key, value in dataframe.iterrows()
        }
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


def add_cohort_annotations(
    team_id: int, breakdown: List[Union[int, str]]
) -> Dict[str, Union[Value, Exists]]:
    cohorts = Cohort.objects.filter(
        team_id=team_id, pk__in=[b for b in breakdown if b != "all"]
    )
    annotations: Dict[str, Union[Value, Exists]] = {}
    for cohort in cohorts:
        annotations["cohort_{}".format(cohort.pk)] = Exists(
            CohortPeople.objects.filter(
                cohort=cohort.pk, person_id=OuterRef("person_id")
            ).only("id")
        )
    if "all" in breakdown:
        annotations["cohort_all"] = Value(True, output_field=BooleanField())
    return annotations


def add_person_properties_annotations(
    team_id: int, breakdown: str
) -> Dict[str, Subquery]:
    person_properties = Subquery(
        Person.objects.filter(team_id=team_id, id=OuterRef("person_id")).values(
            "properties__{}".format(breakdown)
        )
    )
    annotations = {}
    annotations["properties__{}".format(breakdown)] = person_properties
    return annotations


def aggregate_by_interval(
    filtered_events: QuerySet,
    team_id: int,
    entity: Entity,
    filter: Filter,
    interval: str,
    params: dict,
    breakdown: Optional[str] = None,
) -> Dict[str, Any]:
    interval_annotation = get_interval_annotation(interval)
    values = [interval]
    if breakdown:
        breakdown_type = params.get("breakdown_type")
        if breakdown_type == "cohort":
            cohort_annotations = add_cohort_annotations(
                team_id, json.loads(params.get("breakdown", "[]"))
            )
            values.extend(cohort_annotations.keys())
            filtered_events = filtered_events.annotate(**cohort_annotations)
            breakdown = "cohorts"
        elif breakdown_type == "person":
            person_annotations = add_person_properties_annotations(
                team_id, params.get("breakdown", "")
            )
            filtered_events = filtered_events.annotate(**person_annotations)
            values.append(breakdown)
        else:
            values.append(breakdown)
    aggregates = (
        filtered_events.annotate(**interval_annotation)
        .values(*values)
        .annotate(count=Count(1))
        .order_by()
    )

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

    return dates_filled


def process_math(query: QuerySet, entity: Entity):
    if entity.math == "dau":
        query = query.annotate(count=Count("person_id", distinct=True))
    return query


def execute_custom_sql(query, params):
    cursor = connection.cursor()
    cursor.execute(query, params)
    return cursor.fetchall()


def stickiness(
    filtered_events: QuerySet, entity: Entity, filter: Filter, team_id: int
) -> Dict[str, Any]:
    if not filter.date_to or not filter.date_from:
        raise ValueError("_stickiness needs date_to and date_from set")
    range_days = (filter.date_to - filter.date_from).days + 2

    events = (
        filtered_events.filter(filter_events(team_id, filter, entity))
        .values("person_id")
        .annotate(day_count=Count(functions.TruncDay("timestamp"), distinct=True))
        .filter(day_count__lte=range_days)
    )

    events_sql, events_sql_params = events.query.sql_with_params()
    aggregated_query = "select count(v.person_id), v.day_count from ({}) as v group by v.day_count".format(
        events_sql
    )
    aggregated_counts = execute_custom_sql(aggregated_query, events_sql_params)

    response: Dict[int, int] = {}
    for result in aggregated_counts:
        response[result[1]] = result[0]

    labels = []
    data = []

    for day in range(1, range_days):
        label = "{} day{}".format(day, "s" if day > 1 else "")
        labels.append(label)
        data.append(response[day] if day in response else 0)

    return {
        "labels": labels,
        "days": [day for day in range(1, range_days)],
        "data": data,
        "count": sum(data),
    }


def breakdown_label(
    entity: Entity, value: Union[str, int]
) -> Dict[str, Optional[Union[str, int]]]:
    ret_dict: Dict[str, Optional[Union[str, int]]] = {}
    if not value or not isinstance(value, str) or "cohort_" not in value:
        ret_dict["label"] = "{} - {}".format(
            entity.name,
            value if value and value != "None" and value != "nan" else "Other",
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


def serialize_entity(
    entity: Entity, filter: Filter, params: dict, team_id: int
) -> List[Dict[str, Any]]:
    interval = params.get("interval")
    if interval is None:
        interval = "day"

    serialized: Dict[str, Any] = {
        "action": entity.to_dict(),
        "label": entity.name,
        "count": 0,
        "data": [],
        "labels": [],
        "days": [],
    }
    response = []
    events = process_entity_for_events(
        entity=entity,
        team_id=team_id,
        order_by=None if params.get("shown_as") == "Stickiness" else "-timestamp",
    )
    events = events.filter(filter_events(team_id, filter, entity))
    if params.get("shown_as", "Volume") == "Volume":
        items = aggregate_by_interval(
            filtered_events=events,
            team_id=team_id,
            entity=entity,
            filter=filter,
            interval=interval,
            params=params,
            breakdown="properties__{}".format(params.get("breakdown"))
            if params.get("breakdown")
            else None,
        )
        for value, item in items.items():
            new_dict = copy.deepcopy(serialized)
            if value != "Total":
                new_dict.update(breakdown_label(entity, value))
            new_dict.update(
                append_data(dates_filled=list(item.items()), interval=interval)
            )
            if filter.display == TRENDS_CUMULATIVE:
                new_dict["data"] = np.cumsum(new_dict["data"])
            response.append(new_dict)
    elif params.get("shown_as") == TRENDS_STICKINESS:
        new_dict = copy.deepcopy(serialized)
        new_dict.update(
            stickiness(
                filtered_events=events, entity=entity, filter=filter, team_id=team_id
            )
        )
        response.append(new_dict)

    return response


def serialize_people(people: QuerySet, request: request.Request) -> Dict:
    people_dict = [
        PersonSerializer(person, context={"request": request}).data for person in people
    ]
    return {"people": people_dict, "count": len(people_dict)}


def process_entity_for_events(entity: Entity, team_id: int, order_by="-id") -> QuerySet:
    if entity.type == TREND_FILTER_TYPE_ACTIONS:
        events = Event.objects.filter(action__pk=entity.id).add_person_id(team_id)
        if order_by:
            events = events.order_by(order_by)
        return events
    elif entity.type == TREND_FILTER_TYPE_EVENTS:
        return Event.objects.filter_by_event_with_people(
            event=entity.id, team_id=team_id, order_by=order_by
        )
    return QuerySet()


def filter_events(team_id: int, filter: Filter, entity: Optional[Entity] = None) -> Q:
    filters = Q()
    if filter.date_from:
        filters &= Q(timestamp__gte=filter.date_from)
    if filter.date_to:
        relativity = relativedelta(days=1)
        if filter.interval == "hour":
            relativity = relativedelta(hours=1)
        elif filter.interval == "minute":
            relativity = relativedelta(minutes=1)
        elif filter.interval == "week":
            relativity = relativedelta(weeks=1)
        elif filter.interval == "month":
            relativity = (
                relativedelta(months=1) - relativity
            )  # go to last day of month instead of first of next
        filters &= Q(timestamp__lte=filter.date_to + relativity)
    if filter.properties:
        filters &= filter.properties_to_Q(team_id=team_id)
    if entity and entity.properties:
        filters &= entity.properties_to_Q(team_id=team_id)
    return filters


def determine_compared_filter(filter):
    date_from, date_to = get_compare_period_dates(filter.date_from, filter.date_to)
    compared_filter = copy.deepcopy(filter)
    compared_filter._date_from = date_from.date().isoformat()
    compared_filter._date_to = date_to.date().isoformat()
    return compared_filter


def convert_to_comparison(
    trend_entity: List[Dict[str, Any]], filter: Filter, label: str
) -> List[Dict[str, Any]]:
    for entity in trend_entity:
        days = [i for i in range(len(entity["days"]))]
        labels = [
            "{} {}".format(filter.interval if filter.interval is not None else "day", i)
            for i in range(len(entity["labels"]))
        ]
        entity.update(
            {
                "labels": labels,
                "days": days,
                "label": label,
                "dates": entity["days"],
                "compare": True,
            }
        )
    return trend_entity
