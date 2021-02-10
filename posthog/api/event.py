import json
from datetime import timedelta
from typing import Any, Dict, List, Optional, Union, cast

from django.db.models import Prefetch, QuerySet
from django.db.models.query_utils import Q
from django.utils import timezone
from django.utils.timezone import now
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers

from posthog.api.routing import StructuredViewSetMixin
from posthog.constants import DATE_FROM, OFFSET
from posthog.models import Element, ElementGroup, Event, Filter, Person, PersonDistinctId
from posthog.models.action import Action
from posthog.models.event import EventManager
from posthog.models.filters.sessions_filter import SessionEventsFilter, SessionsFilter
from posthog.models.session_recording_event import SessionRecordingViewed
from posthog.permissions import ProjectMembershipNecessaryPermissions
from posthog.queries.base import properties_to_Q
from posthog.queries.sessions.session_recording import SessionRecording
from posthog.utils import convert_property_value, flatten, relative_date_parse


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

    def get_elements(self, event: Event):
        if not event.elements_hash:
            return []
        if hasattr(event, "elements_group_cache"):
            if event.elements_group_cache:  # type: ignore
                return ElementSerializer(
                    event.elements_group_cache.element_set.all().order_by("order"),  # type: ignore
                    many=True,
                ).data
        elements = (
            ElementGroup.objects.get(hash=event.elements_hash, team_id=event.team_id)
            .element_set.all()
            .order_by("order")
        )
        return ElementSerializer(elements, many=True).data

    def to_representation(self, instance):
        representation = super(EventSerializer, self).to_representation(instance)
        if self.context.get("format") == "csv":
            representation.pop("elements")
        return representation


class EventViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    legacy_team_compatibility = True  # to be moved to a separate Legacy*ViewSet Class

    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES) + (csvrenderers.PaginatedCSVRenderer,)
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions]

    def get_queryset(self):
        queryset = cast(EventManager, super().get_queryset()).add_person_id(self.team_id)

        if self.action == "list" or self.action == "sessions" or self.action == "actions":
            queryset = self._filter_request(self.request, queryset)

        order_by = self.request.GET.get("orderBy")
        order_by = ["-timestamp"] if not order_by else list(json.loads(order_by))
        return queryset.order_by(*order_by)

    def _filter_request(self, request: request.Request, queryset: EventManager) -> QuerySet:
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
                queryset = queryset.filter(properties_to_Q(filter.properties, team_id=self.team_id))
        return queryset

    def _prefetch_events(self, events: List[Event]) -> List[Event]:
        team_id = self.team_id
        distinct_ids = []
        hash_ids = []
        for event in events:
            distinct_ids.append(event.distinct_id)
            if event.elements_hash:
                hash_ids.append(event.elements_hash)
        people = Person.objects.filter(
            team_id=team_id, persondistinctid__distinct_id__in=distinct_ids
        ).prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))
        if len(hash_ids) > 0:
            groups = ElementGroup.objects.filter(team_id=team_id, hash__in=hash_ids).prefetch_related("element_set")
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
        # don't allow events too far into the future
        queryset = queryset.filter(timestamp__lte=now() + timedelta(seconds=5),)
        events = queryset.filter(timestamp__gte=monday.replace(hour=0, minute=0, second=0))[0:101]

        is_csv_request = self.request.accepted_renderer.format == "csv"

        if not is_csv_request and len(events) < 101:
            events = queryset[0:101]
        elif is_csv_request:
            events = queryset[0:100000]

        prefetched_events = self._prefetch_events([event for event in events])
        path = request.get_full_path()

        reverse = request.GET.get("orderBy", "-timestamp") != "-timestamp"
        if not is_csv_request and len(events) > 100:
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

        return response.Response(
            {
                "next": next_url,
                "results": EventSerializer(
                    prefetched_events[0:100], many=True, context={"format": self.request.accepted_renderer.format}
                ).data,
            }
        )

    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request, **kwargs) -> response.Response:
        result = self.get_values(request)
        return response.Response(result)

    def get_values(self, request: request.Request) -> List[Dict[str, Any]]:
        key = request.GET.get("key")
        params: List[Optional[Union[str, int]]] = [key, key]

        if key == "custom_event":
            event_names = (
                Event.objects.filter(team_id=self.team_id)
                .filter(~Q(event__in=["$autocapture", "$pageview", "$identify", "$pageleave", "$screen"]))
                .values("event")
                .distinct()
            )
            return [{"name": value["event"]} for value in event_names]

        if request.GET.get("value"):
            where = " AND properties ->> %s LIKE %s"
            params.append(key)
            params.append("%{}%".format(request.GET["value"]))
        else:
            where = ""

        params.append(self.team_id)
        params.append(relative_date_parse("-7d").strftime("%Y-%m-%d 00:00:00"))
        params.append(timezone.now().strftime("%Y-%m-%d 23:59:59"))

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
                    ("posthog_event"."team_id" = %s) AND
                    ("posthog_event"."timestamp" >= %s) AND
                    ("posthog_event"."timestamp" <= %s)
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

        flattened = flatten([value.value for value in values])
        return [{"name": convert_property_value(value)} for value in flattened]

    # ******************************************
    # /event/sessions
    #
    # params:
    # - pagination: (dict) Object containing information about pagination (offset, last page info)
    # - distinct_id: (string) filter sessions by distinct id
    # - duration: (float) filter sessions by recording duration
    # - duration_operator: (string: lt, gt)
    # - **shared filter types
    # ******************************************
    @action(methods=["GET"], detail=False)
    def sessions(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        from posthog.queries.sessions.sessions_list import SessionsList

        filter = SessionsFilter(request=request)
        pagination = json.loads(request.GET.get("pagination", "{}"))

        sessions, pagination = SessionsList().run(filter=filter, team=self.team, **pagination)

        if filter.distinct_id:
            sessions = self._filter_sessions_by_distinct_id(filter.distinct_id, sessions)

        return Response({"result": sessions, "pagination": pagination})

    def _filter_sessions_by_distinct_id(self, distinct_id: str, sessions: List[Any]) -> List[Any]:
        person_ids = Person.objects.get(team=self.team, persondistinctid__distinct_id=distinct_id).distinct_ids
        return [session for i, session in enumerate(sessions) if session["distinct_id"] in person_ids]

    @action(methods=["GET"], detail=False)
    def session_events(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        from posthog.queries.sessions.sessions_list_events import SessionsListEvents

        filter = SessionEventsFilter(request=request)
        return Response({"result": SessionsListEvents().run(filter=filter, team=self.team)})

    # ******************************************
    # /event/session_recording
    # params:
    # - session_recording_id: (string) id of the session recording
    # - save_view: (boolean) save view of the recording
    # ******************************************
    @action(methods=["GET"], detail=False)
    def session_recording(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        session_recording = SessionRecording().run(
            team=self.team, filter=Filter(request=request), session_recording_id=request.GET["session_recording_id"]
        )

        if request.GET.get("save_view"):
            SessionRecordingViewed.objects.get_or_create(
                team=self.team, user=request.user, session_id=request.GET["session_recording_id"]
            )

        return response.Response({"result": session_recording})
