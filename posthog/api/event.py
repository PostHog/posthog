import json
import urllib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union, cast

from django.db.models import Prefetch, QuerySet
from django.db.models.query_utils import Q
from django.utils import timezone
from django.utils.timezone import now
from rest_framework import mixins, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers

from posthog.api.routing import StructuredViewSetMixin
from posthog.models import Element, ElementGroup, Event, Filter, Person, PersonDistinctId
from posthog.models.action import Action
from posthog.models.event import EventManager
from posthog.models.filters.sessions_filter import SessionEventsFilter, SessionsFilter
from posthog.models.session_recording_event import SessionRecordingViewed
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
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
    elements = serializers.SerializerMethodField()
    person = serializers.SerializerMethodField()

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
        if hasattr(event, "serialized_person"):
            return event.serialized_person  # type: ignore
        return None

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


class EventViewSet(StructuredViewSetMixin, mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES) + (csvrenderers.PaginatedCSVRenderer,)
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    pagination_class = LimitOffsetPagination
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]

    # Return at most this number of events in CSV export
    CSV_EXPORT_DEFAULT_LIMIT = 10_000
    CSV_EXPORT_MAXIMUM_LIMIT = 100_000

    def get_queryset(self):
        queryset = cast(EventManager, super().get_queryset()).add_person_id(self.team_id)
        if self.action == "list" or self.action == "sessions" or self.action == "actions":
            queryset = self._filter_request(self.request, queryset)
        order_by_param = self.request.GET.get("orderBy")
        order_by = ["-timestamp"] if not order_by_param else list(json.loads(order_by_param))
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
                queryset = queryset.filter(
                    distinct_id__in=PersonDistinctId.objects.filter(
                        team_id=self.team_id, person_id=request.GET["person_id"]
                    ).values("distinct_id")
                )
            elif key == "distinct_id":
                queryset = queryset.filter(distinct_id=request.GET["distinct_id"])
            elif key == "action_id":
                queryset = queryset.filter_by_action(Action.objects.get(pk=value))  # type: ignore
            elif key == "properties":
                try:
                    properties = json.loads(value)
                except json.decoder.JSONDecodeError:
                    raise ValidationError("Properties are unparsable!")

                filter = Filter(data={"properties": properties})
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
                for person in people:
                    if event.distinct_id in person.distinct_ids:
                        event.serialized_person = {  # type: ignore
                            "is_identified": person.is_identified,
                            "distinct_ids": [
                                person.distinct_ids[0],
                            ],  # only send the first one to avoid a payload bloat
                            "properties": {
                                key: person.properties[key]
                                for key in ["email", "name", "username"]
                                if key in person.properties
                            },
                        }
                        break
            except IndexError:
                event.serialized_person = None  # type: ignore
            try:
                event.elements_group_cache = [group for group in groups if group.hash == event.elements_hash][0]  # type: ignore
            except IndexError:
                event.elements_group_cache = None  # type: ignore
        return events

    def _build_next_url(self, request: request.Request, last_event_timestamp: datetime) -> str:
        params = request.GET.dict()
        reverse = request.GET.get("orderBy", "-timestamp") != "-timestamp"
        timestamp = last_event_timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        try:
            del params["after"]
        except KeyError:
            pass
        try:
            del params["before"]
        except KeyError:
            pass

        return request.build_absolute_uri(
            "{}?{}{}{}={}".format(
                request.path,
                urllib.parse.urlencode(params),
                "&" if len(params) > 0 else "",
                "after" if reverse else "before",
                timestamp,
            )
        )

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        is_csv_request = self.request.accepted_renderer.format == "csv"
        monday = now() + timedelta(days=-now().weekday())
        # Don't allow events too far into the future
        queryset = self.get_queryset().filter(timestamp__lte=now() + timedelta(seconds=5))
        next_url: Optional[str] = None

        if self.request.GET.get("limit", None):
            limit = int(self.request.GET.get("limit"))  # type: ignore
        elif is_csv_request:
            limit = self.CSV_EXPORT_DEFAULT_LIMIT
        else:
            limit = 100

        if is_csv_request:
            limit = min(limit, self.CSV_EXPORT_MAXIMUM_LIMIT)
            events = queryset[:limit]
        else:
            events = queryset.filter(timestamp__gte=monday.replace(hour=0, minute=0, second=0))[: (limit + 1)]
            if len(events) < limit + 1:
                events = queryset[: limit + 1]

            if len(events) > limit:
                next_url = self._build_next_url(request, events[limit - 1].timestamp)

            events = self.paginator.paginate_queryset(events, request, view=self)  # type: ignore

        prefetched_events = self._prefetch_events(list(events))

        return response.Response(
            {
                "next": next_url,
                "results": EventSerializer(
                    prefetched_events, many=True, context={"format": self.request.accepted_renderer.format}
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
        flattened = flatten([json.loads(value.value) for value in values])
        return [{"name": convert_property_value(value)} for value in flattened]

    # ******************************************
    # /events/sessions
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

        filter = SessionsFilter(request=request, team=self.team)

        sessions, pagination = SessionsList.run(filter=filter, team=self.team)
        return Response({"result": sessions, "pagination": pagination})

    @action(methods=["GET"], detail=False)
    def session_events(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        from posthog.queries.sessions.sessions_list_events import SessionsListEvents

        filter = SessionEventsFilter(request=request, team=self.team)
        return Response({"result": SessionsListEvents().run(filter=filter, team=self.team)})

    # ******************************************
    # /events/session_recording
    # params:
    # - session_recording_id: (string) id of the session recording
    # - save_view: (boolean) save view of the recording
    # ******************************************
    @action(methods=["GET"], detail=False)
    def session_recording(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        if not request.GET.get("session_recording_id"):
            return Response(
                {
                    "detail": "The query parameter session_recording_id is required for this endpoint.",
                    "type": "validation_error",
                    "code": "invalid",
                },
                status=400,
            )
        session_recording = SessionRecording(
            request=request,
            filter=Filter(request=request, team=self.team),
            session_recording_id=request.GET["session_recording_id"],
            team=self.team,
        ).run()

        if request.GET.get("save_view"):
            SessionRecordingViewed.objects.get_or_create(
                team=self.team, user=request.user, session_id=request.GET["session_recording_id"]
            )

        return response.Response({"result": session_recording})


class LegacyEventViewSet(EventViewSet):
    legacy_team_compatibility = True
