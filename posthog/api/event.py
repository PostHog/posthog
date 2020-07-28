from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from posthog.models import (
    Event,
    Person,
    Element,
    Action,
    ElementGroup,
    Filter,
    PersonDistinctId,
    Team,
)
from posthog.utils import (
    friendly_time,
    request_to_date_query,
    append_data,
    convert_property_value,
    get_compare_period_dates,
    dict_from_cursor_fetchall,
)
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from django.db.models import QuerySet, F, Prefetch, Q
from django.db.models.functions import Lag
from django.db.models.expressions import Window
from django.db import connection
from django.utils.timezone import now
from typing import Any, Dict, List, Optional
from django.utils.timezone import now
import json
import pandas as pd
from typing import Tuple, Optional


class ElementSerializer(serializers.ModelSerializer):
    event = serializers.CharField()

    class Meta:
        model = Element
        fields = [
            "event",
            "text",
            "tag_name",
            "attr_class",
            "href",
            "attr_id",
            "nth_child",
            "nth_of_type",
            "attributes",
            "order",
        ]


class EventSerializer(serializers.HyperlinkedModelSerializer):
    person = serializers.SerializerMethodField()
    elements = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            "id",
            "distinct_id",
            "properties",
            "elements",
            "event",
            "timestamp",
            "person",
        ]

    def get_person(self, event: Event) -> Any:
        if hasattr(event, "person_properties"):
            if event.person_properties:  # type: ignore
                return event.person_properties.get("email", event.distinct_id)  # type: ignore
            else:
                return event.distinct_id
        try:
            return event.person.properties.get("email", event.distinct_id)
        except:
            return event.distinct_id

    def get_elements(self, event):
        if not event.elements_hash:
            return []
        if hasattr(event, "elements_group_cache"):
            if event.elements_group_cache:
                return ElementSerializer(
                    event.elements_group_cache.element_set.all().order_by("order"), many=True,
                ).data
        elements = ElementGroup.objects.get(hash=event.elements_hash).element_set.all().order_by("order")
        return ElementSerializer(elements, many=True).data


class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()

        team = self.request.user.team_set.get()
        queryset = queryset.add_person_id(team.pk)  # type: ignore

        if self.action == "list" or self.action == "sessions" or self.action == "actions":  # type: ignore
            queryset = self._filter_request(self.request, queryset, team)

        order_by = self.request.GET.get("orderBy")
        order_by = ["-timestamp"] if not order_by else list(json.loads(order_by))
        return queryset.filter(team=team).order_by(*order_by)

    def _filter_request(self, request: request.Request, queryset: QuerySet, team: Team) -> QuerySet:
        for key, value in request.GET.items():
            if key == "event":
                queryset = queryset.filter(event=request.GET["event"])
            elif key == "after":
                queryset = queryset.filter(timestamp__gt=request.GET["after"])
            elif key == "before":
                queryset = queryset.filter(timestamp__lt=request.GET["before"])
            elif key == "person_id":
                person = Person.objects.get(pk=request.GET["person_id"])
                queryset = queryset.filter(
                    distinct_id__in=PersonDistinctId.objects.filter(person_id=request.GET["person_id"]).values(
                        "distinct_id"
                    )
                )
            elif key == "distinct_id":
                queryset = queryset.filter(distinct_id=request.GET["distinct_id"])
            elif key == "action_id":
                queryset = queryset.filter_by_action(Action.objects.get(pk=value))  # type: ignore
            elif key == "properties":
                filter = Filter(data={"properties": json.loads(value)})
                queryset = queryset.filter(filter.properties_to_Q(team_id=team.pk))
        return queryset

    def _serialize_actions(self, event: Event) -> Dict:
        return {
            "id": "{}-{}".format(event.action.pk, event.id),  # type: ignore
            "event": EventSerializer(event).data,
            "action": {
                "name": event.action.name,  # type: ignore
                "id": event.action.pk,  # type: ignore
            },
        }

    def _prefetch_events(self, events: List[Event]) -> List[Event]:
        team = self.request.user.team_set.get()
        distinct_ids = []
        hash_ids = []
        for event in events:
            distinct_ids.append(event.distinct_id)
            if event.elements_hash:
                hash_ids.append(event.elements_hash)
        people = Person.objects.filter(team=team, persondistinctid__distinct_id__in=distinct_ids).prefetch_related(
            Prefetch("persondistinctid_set", to_attr="distinct_ids_cache")
        )
        if len(hash_ids) > 0:
            groups = ElementGroup.objects.filter(team=team, hash__in=hash_ids).prefetch_related("element_set")
        else:
            groups = ElementGroup.objects.none()
        for event in events:
            try:
                event.person_properties = [person.properties for person in people if event.distinct_id in person.distinct_ids][0]  # type: ignore
            except IndexError:
                event.person_properties = None  # type: ignore
            try:
                event.elements_group_cache = [group for group in groups if group.hash == event.elements_hash][0]  # type: ignore
            except IndexError:
                event.elements_group_cache = None  # type: ignore
        return events

    def _prefech_elements(self, hash_ids: List[str], team: Team) -> QuerySet:
        groups = ElementGroup.objects.none()
        if len(hash_ids) > 0:
            groups = ElementGroup.objects.filter(team=team, hash__in=hash_ids).prefetch_related("element_set")
        return groups

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        queryset = self.get_queryset()
        monday = now() + timedelta(days=-now().weekday())
        events = queryset.filter(timestamp__gte=monday.replace(hour=0, minute=0, second=0))[0:101]

        if len(events) < 101:
            events = queryset[0:101]

        prefetched_events = self._prefetch_events([event for event in events])
        path = request.get_full_path()

        reverse = request.GET.get("orderBy", "-timestamp") != "-timestamp"
        if len(events) > 100:
            next_url: Optional[str] = request.build_absolute_uri(
                "{}{}{}={}".format(
                    path,
                    "&" if "?" in path else "?",
                    "after" if reverse else "before",
                    events[99].timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                )
            )
        else:
            next_url = None

        return response.Response({"next": next_url, "results": EventSerializer(prefetched_events, many=True).data,})

    @action(methods=["GET"], detail=False)
    def actions(self, request: request.Request) -> response.Response:
        events = (
            self.get_queryset()
            .filter(action__deleted=False, action__isnull=False)
            .prefetch_related(Prefetch("action_set", queryset=Action.objects.filter(deleted=False).order_by("id")))[
                0:101
            ]
        )
        matches = []
        ids_seen: List[int] = []
        for event in events:
            if event.pk in ids_seen:
                continue
            ids_seen.append(event.pk)
            for action in event.action_set.all():
                event.action = action
                matches.append(event)
        prefetched_events = self._prefetch_events(matches)
        return response.Response(
            {"next": len(events) > 100, "results": [self._serialize_actions(event) for event in prefetched_events],}
        )

    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request) -> response.Response:
        key = request.GET.get("key")
        params = [key, key]
        if request.GET.get("value"):
            where = " AND properties ->> %s LIKE %s"
            params.append(key)
            params.append("%{}%".format(request.GET["value"]))
        else:
            where = ""

        params.append(request.user.team_set.get().pk)
        # This samples a bunch of events with that property, and then orders them by most popular in that sample
        # This is much quicker than trying to do this over the entire table
        values = Event.objects.raw(
            """
            SELECT
                value, COUNT(1) as id
            FROM ( 
                SELECT
                    ("posthog_event"."properties" -> %s) as "value"
                FROM
                    "posthog_event"
                WHERE
                    ("posthog_event"."properties" -> %s) IS NOT NULL {} AND
                    ("posthog_event"."team_id" = %s)
                LIMIT 10000
            ) as "value"
            GROUP BY value
            ORDER BY id DESC
            LIMIT 50;
        """.format(
                where
            ),
            params,
        )

        return response.Response([{"name": convert_property_value(value.value)} for value in values])

    def _handle_compared(self, date_filter: Dict[str, datetime]) -> QuerySet:
        date_from, date_to = get_compare_period_dates(date_filter["timestamp__gte"], date_filter["timestamp__lte"])
        date_filter["timestamp__gte"] = date_from
        date_filter["timestamp__lte"] = date_to
        compared_events = self.get_queryset().filter(**date_filter)
        return compared_events

    def _convert_to_comparison(self, trend_entity: List[Dict[str, Any]], label: str) -> List[Dict[str, Any]]:
        for entity in trend_entity:
            days = [i for i in range(len(entity["days"]))]
            labels = ["{} {}".format("Day", i) for i in range(len(entity["labels"]))]
            entity.update(
                {
                    "labels": labels,
                    "days": days,
                    "chartLabel": "{} - {}".format(entity["label"], label),
                    "dates": entity["days"],
                    "compare": True,
                }
            )
        return trend_entity

    @action(methods=["GET"], detail=False)
    def sessions(self, request: request.Request) -> response.Response:
        team = self.request.user.team_set.get()
        session_type = self.request.GET.get("session")

        date_filter = request_to_date_query(request.GET.dict(), exact=True)
        if not date_filter.get("timestamp__gte"):
            date_filter["timestamp__gte"] = (
                Event.objects.filter(team=team)
                .order_by("timestamp")[0]
                .timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
            )

        if not date_filter.get("timestamp__lte"):
            date_filter["timestamp__lte"] = now()

        events = self.get_queryset()
        if session_type is not None:
            events = events.filter(**date_filter)

        calculated = []

        # get compared period
        compare = request.GET.get("compare")
        result: Dict[str, Any] = {"result": []}
        if compare and request.GET.get("date_from") != "all" and session_type == "avg":
            calculated = self.calculate_sessions(events, session_type, date_filter, team, request)
            calculated = self._convert_to_comparison(calculated, "current")
            compared_events = self._handle_compared(date_filter)
            compared_calculated = self.calculate_sessions(compared_events, session_type, date_filter, team, request)
            converted_compared_calculated = self._convert_to_comparison(compared_calculated, "previous")
            calculated.extend(converted_compared_calculated)
        else:
            calculated = self.calculate_sessions(events, session_type, date_filter, team, request)
        result.update({"result": calculated})

        # add pagination
        if session_type is None:
            offset = int(request.GET.get("offset", "0")) + 50
            if len(calculated) > 49:
                date_from = calculated[0]["start_time"].isoformat()
                result.update({"offset": offset})
                result.update({"date_from": date_from})
        return response.Response(result)

    def calculate_sessions(
        self,
        events: QuerySet,
        session_type: Optional[str],
        date_filter: Dict[str, datetime],
        team: Team,
        request: request.Request,
    ) -> List[Dict[str, Any]]:

        # format date filter for session view
        _date_gte = Q()
        if session_type is None:
            if request.GET.get("date_from", None):
                _date_gte = Q(
                    timestamp__gte=date_filter["timestamp__gte"],
                    timestamp__lte=date_filter["timestamp__gte"] + relativedelta(days=1),
                )
            else:
                dt = datetime.now()
                dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
                _date_gte = Q(timestamp__gte=dt, timestamp__lte=dt + relativedelta(days=1))

        sessions = (
            events.filter(_date_gte)
            .annotate(
                previous_timestamp=Window(
                    expression=Lag("timestamp", default=None),
                    partition_by=F("distinct_id"),
                    order_by=F("timestamp").asc(),
                )
            )
            .annotate(
                previous_event=Window(
                    expression=Lag("event", default=None), partition_by=F("distinct_id"), order_by=F("timestamp").asc(),
                )
            )
        )

        sessions_sql, sessions_sql_params = sessions.query.sql_with_params()
        all_sessions = "\
            SELECT *,\
                SUM(new_session) OVER (ORDER BY distinct_id, timestamp) AS global_session_id,\
                SUM(new_session) OVER (PARTITION BY distinct_id ORDER BY timestamp) AS user_session_id\
                FROM (SELECT id, distinct_id, event, elements_hash, timestamp, properties, CASE WHEN EXTRACT('EPOCH' FROM (timestamp - previous_timestamp)) >= (60 * 30)\
                    OR previous_timestamp IS NULL \
                    THEN 1 ELSE 0 END AS new_session \
                    FROM ({}) AS inner_sessions\
                ) AS outer_sessions".format(
            sessions_sql
        )

        result: List = []
        interval = request.GET.get("interval", None)
        if session_type == "avg":
            result = self._session_avg(all_sessions, sessions_sql_params, date_filter, interval)
        elif session_type == "dist":
            result = self._session_dist(all_sessions, sessions_sql_params)
        else:
            result = self._session_list(all_sessions, sessions_sql_params, team, request)

        return result

    def _session_list(
        self, base_query: str, params: Tuple[Any, ...], team: Team, request: request.Request,
    ) -> List[Dict[str, Any]]:
        session_list = "SELECT * FROM (SELECT global_session_id, properties, start_time, length, sessions.distinct_id, event_count, events from\
                                (SELECT\
                                    global_session_id,\
                                    count(1) as event_count,\
                                    MAX(distinct_id) as distinct_id,\
                                    EXTRACT('EPOCH' FROM (MAX(timestamp) - MIN(timestamp))) AS length,\
                                    MIN(timestamp) as start_time,\
                                    array_agg(json_build_object( 'id', id, 'event', event, 'timestamp', timestamp, 'properties', properties, 'elements_hash', elements_hash) ORDER BY timestamp) as events\
                                        FROM ({}) as count GROUP BY 1) as sessions\
                                        LEFT OUTER JOIN posthog_persondistinctid ON posthog_persondistinctid.distinct_id = sessions.distinct_id\
                                        LEFT OUTER JOIN posthog_person ON posthog_person.id = posthog_persondistinctid.person_id\
                                        ORDER BY start_time DESC) as ordered_sessions OFFSET %s LIMIT 50".format(
            base_query
        )

        with connection.cursor() as cursor:
            offset = request.GET.get("offset", 0)
            params = params + (offset,)
            cursor.execute(session_list, params)
            sessions = dict_from_cursor_fetchall(cursor)

            hash_ids = []
            for session in sessions:
                for event in session["events"]:
                    if event.get("elements_hash"):
                        hash_ids.append(event["elements_hash"])

            groups = self._prefech_elements(hash_ids, team)

            for session in sessions:
                for event in session["events"]:
                    try:
                        event.update(
                            {
                                "elements": ElementSerializer(
                                    [group for group in groups if group.hash == event["elements_hash"]][0]
                                    .element_set.all()
                                    .order_by("order"),
                                    many=True,
                                ).data
                            }
                        )
                    except IndexError:
                        event.update({"elements": []})
            result = sessions
        return result

    def _session_avg(
        self, base_query: str, params: Tuple[Any, ...], date_filter: Dict[str, datetime], interval: Optional[str]
    ) -> List[Dict[str, Any]]:
        def _determineInterval(interval):
            if interval == "minute":
                return (
                    "minute",
                    "min",
                )
            elif interval == "hour":
                return "hour", "H"
            elif interval == "week":
                return "week", "W"
            elif interval == "month":
                return "month", "M"
            else:
                return "day", "D"

        interval, interval_freq = _determineInterval(interval)

        average_length_time = "SELECT date_trunc('{interval}', timestamp) as start_time,\
                        AVG(length) AS average_session_length_per_day,\
                        SUM(length) AS total_session_length_per_day, \
                        COUNT(1) as num_sessions_per_day\
                        FROM (SELECT global_session_id, EXTRACT('EPOCH' FROM (MAX(timestamp) - MIN(timestamp)))\
                            AS length,\
                            MIN(timestamp) as timestamp FROM ({}) as count GROUP BY 1) as agg group by 1 order by start_time".format(
            base_query, interval=interval
        )

        cursor = connection.cursor()
        cursor.execute(average_length_time, params)
        time_series_avg = cursor.fetchall()

        date_range = pd.date_range(date_filter["timestamp__gte"], date_filter["timestamp__lte"], freq=interval_freq,)
        df = pd.DataFrame([{"date": a[0], "count": a[1], "breakdown": "Total"} for a in time_series_avg])
        if interval == "week":
            df["date"] = df["date"].apply(lambda x: x - pd.offsets.Week(weekday=6))
        elif interval == "month":
            df["date"] = df["date"].apply(lambda x: x - pd.offsets.MonthEnd(n=0))

        df_dates = pd.DataFrame(df.groupby("date").mean(), index=date_range)
        df_dates = df_dates.fillna(0)
        values = [(key, round(value[0])) if len(value) > 0 else (key, 0) for key, value in df_dates.iterrows()]

        time_series_data = append_data(values, interval=interval, math=None)
        # calculate average
        totals = [sum(x) for x in list(zip(*time_series_avg))[2:4]]
        overall_average = (totals[0] / totals[1]) if totals else 0
        avg_formatted = friendly_time(overall_average)
        avg_split = avg_formatted.split(" ")

        time_series_data.update(
            {"label": "Average Duration of Session ({})".format(avg_split[1]), "count": int(avg_split[0]),}
        )
        time_series_data.update({"chartLabel": "Average Duration of Session (seconds)"})
        result = [time_series_data]
        return result

    def _session_dist(self, base_query: str, params: Tuple[Any, ...]) -> List[Dict[str, Any]]:
        distribution = "SELECT COUNT(CASE WHEN length = 0 THEN 1 ELSE NULL END) as first,\
                        COUNT(CASE WHEN length > 0 AND length <= 3 THEN 1 ELSE NULL END) as second,\
                        COUNT(CASE WHEN length > 3 AND length <= 10 THEN 1 ELSE NULL END) as third,\
                        COUNT(CASE WHEN length > 10 AND length <= 30 THEN 1 ELSE NULL END) as fourth,\
                        COUNT(CASE WHEN length > 30 AND length <= 60 THEN 1 ELSE NULL END) as fifth,\
                        COUNT(CASE WHEN length > 60 AND length <= 180 THEN 1 ELSE NULL END) as sixth,\
                        COUNT(CASE WHEN length > 180 AND length <= 600 THEN 1 ELSE NULL END) as seventh,\
                        COUNT(CASE WHEN length > 600 AND length <= 1800 THEN 1 ELSE NULL END) as eighth,\
                        COUNT(CASE WHEN length > 1800 AND length <= 3600 THEN 1 ELSE NULL END) as ninth,\
                        COUNT(CASE WHEN length > 3600 THEN 1 ELSE NULL END) as tenth\
                        FROM (SELECT global_session_id, EXTRACT('EPOCH' FROM (MAX(timestamp) - MIN(timestamp)))\
                            AS length FROM ({}) as count GROUP BY 1) agg".format(
            base_query
        )

        dist_labels = [
            "0 seconds (1 event)",
            "0-3 seconds",
            "3-10 seconds",
            "10-30 seconds",
            "30-60 seconds",
            "1-3 minutes",
            "3-10 minutes",
            "10-30 minutes",
            "30-60 minutes",
            "1+ hours",
        ]
        cursor = connection.cursor()
        cursor.execute(distribution, params)
        calculated = cursor.fetchall()
        result = [{"label": dist_labels[index], "count": calculated[0][index]} for index in range(len(dist_labels))]
        return result
