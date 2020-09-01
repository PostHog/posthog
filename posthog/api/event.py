import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd
from dateutil.relativedelta import relativedelta
from django.db import connection
from django.db.models import F, Prefetch, Q, QuerySet
from django.db.models.expressions import Window
from django.db.models.functions import Lag
from django.utils.timezone import now
from rest_framework import exceptions, request, response, serializers, viewsets
from rest_framework.decorators import action

from posthog.constants import DATE_FROM, OFFSET
from posthog.models import (
    Action,
    Element,
    ElementGroup,
    Event,
    Filter,
    Person,
    PersonDistinctId,
    Team,
)
from posthog.queries.sessions import Sessions
from posthog.utils import (
    append_data,
    convert_property_value,
    dict_from_cursor_fetchall,
    friendly_time,
    get_compare_period_dates,
    request_to_date_query,
)


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

        team = self.request.user.team
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

    @staticmethod
    def serialize_actions(event: Event) -> Dict:
        return {
            "id": "{}-{}".format(event.action.pk, event.id),  # type: ignore
            "event": EventSerializer(event).data,
            "action": {
                "name": event.action.name,  # type: ignore
                "id": event.action.pk,  # type: ignore
            },
        }

    def _prefetch_events(self, events: List[Event]) -> List[Event]:
        team = self.request.user.team
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
        action_id, action_id_raw = None, request.query_params.get("id")
        if action_id_raw is not None:
            try:
                action_id = int(action_id_raw)
            except (TypeError, ValueError):
                raise exceptions.ValidationError(detail="Invalid query param `id`.")
        extra_event_filters = {}
        if action_id is not None:
            extra_event_filters["action__id"] = action_id
        events = (
            self.get_queryset()
            .filter(action__deleted=False, action__isnull=False, **extra_event_filters)
            .prefetch_related(Prefetch("action_set", queryset=Action.objects.filter(deleted=False).order_by("id")))[
                0:101
            ]
        )
        matches = []
        ids_seen: Set[int] = set()
        for event in events:
            if event.pk in ids_seen:
                continue
            ids_seen.add(event.pk)
            for this_action in event.action_set.all():
                event.action = this_action
                matches.append(event)
        prefetched_events = self._prefetch_events(matches)
        return response.Response(
            {"next": len(events) > 100, "results": [self.serialize_actions(event) for event in prefetched_events],}
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

        params.append(request.user.team.pk)
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

    @action(methods=["GET"], detail=False)
    def sessions(self, request: request.Request) -> response.Response:
        team = self.request.user.team

        filter = Filter(request=request)
        result: Dict[str, Any] = {"result": Sessions().run(filter, team)}

        # add pagination
        if filter.session_type is None:
            offset = filter.offset + 50
            if len(result["result"]) > 49:
                date_from = result["result"][0]["start_time"].isoformat()
                result.update({OFFSET: offset})
                result.update({DATE_FROM: date_from})
        return response.Response(result)
