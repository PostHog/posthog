from posthog.models import Event, Team, Person, Element, Action, PersonDistinctId, ElementGroup
from posthog.utils import properties_to_Q
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from django.http import HttpResponse, JsonResponse
from django.db.models import Q, Count, QuerySet, query, F, Func, functions, Prefetch
from django.forms.models import model_to_dict
from typing import Any, Union, Tuple, Dict, List
import re
import json

class ElementSerializer(serializers.ModelSerializer):
    event = serializers.CharField()
    class Meta:
        model = Element
        fields = ['event', 'text', 'tag_name', 'attr_class', 'href', 'attr_id', 'nth_child', 'nth_of_type', 'attributes', 'order']

class EventSerializer(serializers.HyperlinkedModelSerializer):
    person = serializers.SerializerMethodField()
    elements = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = ['id', 'distinct_id', 'properties', 'elements', 'event', 'timestamp', 'person']

    def get_person(self, event: Event) -> Any:
        if hasattr(event, 'person_properties'):
            if event.person_properties: # type: ignore
                return event.person_properties.get('email', event.distinct_id) # type: ignore
            else:
                return event.distinct_id
        try:
            return event.person.properties.get('email', event.distinct_id)
        except:
            return event.distinct_id

    def get_elements(self, event):
        if not event.elements_hash:
            return []
        if hasattr(event, 'elements_group'):
            if event.elements_group:
                return ElementSerializer(event.elements_group.element_set.all().order_by('order'), many=True).data
        elements = ElementGroup.objects.get(hash=event.elements_hash).element_set.all().order_by('order')
        return ElementSerializer(elements, many=True).data

class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == 'list': # type: ignore
            queryset = self._filter_request(self.request, queryset)

        return queryset\
            .filter(team=self.request.user.team_set.get())\
            .order_by('-timestamp')

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        for key, value in request.GET.items():
            if key == 'event':
                queryset = queryset.filter(event=request.GET['event'])
            elif key == 'after':
                queryset = queryset.filter(timestamp__gt=request.GET['after'])
            elif key == 'before':
                queryset = queryset.filter(timestamp__lt=request.GET['before'])
            elif key == 'person_id':
                person = Person.objects.get(pk=request.GET['person_id'])
                queryset = queryset.filter(distinct_id__in=person.distinct_ids)
            elif key == 'distinct_id':
                queryset = queryset.filter(distinct_id=request.GET['distinct_id'])
            elif key == 'action_id':
                queryset = queryset.filter_by_action(Action.objects.get(pk=value)) # type: ignore
            elif key == 'properties':
                queryset = queryset.filter(properties_to_Q(json.loads(value)))
        return queryset

    def _serialize_actions(self, event: Event) -> Dict:
        return {
            'id': "{}-{}".format(event.action.pk, event.id), # type: ignore
            'event': EventSerializer(event).data,
            'action': {
                'name': event.action.name, # type: ignore
                'id': event.action.pk # type: ignore
            }
        }

    def _prefetch_events(self, events: List[Event]) -> List[Event]:
        team = self.request.user.team_set.get()
        distinct_ids = []
        hash_ids = []
        for event in events:
            distinct_ids.append(event.distinct_id)
            if event.elements_hash:
                hash_ids.append(event.elements_hash)
        people = Person.objects.filter(team=team, persondistinctid__distinct_id__in=distinct_ids).prefetch_related(Prefetch('persondistinctid_set', to_attr='distinct_ids_cache'))
        if len(hash_ids) > 0:
            groups = ElementGroup.objects.filter(team=team, hash__in=hash_ids).prefetch_related('element_set')
        else:
            groups = ElementGroup.objects.none()
        for event in events:
            try:
                event.person_properties = [person.properties for person in people if event.distinct_id in person.distinct_ids][0] # type: ignore
            except IndexError:
                event.person_properties = None # type: ignore
            try:
                event.elements_group = [group for group in groups if group.hash == event.elements_hash][0] # type: ignore
            except IndexError:
                event.elements_group = None # type: ignore
        return events

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        events = [event for event in self.get_queryset()[0: 101]]
        prefetched_events = self._prefetch_events(events[0:100])
        return response.Response({
            'next': len(events) > 100,
            'results': EventSerializer(prefetched_events, many=True).data
        })

    @action(methods=['GET'], detail=False)
    def actions(self, request: request.Request) -> response.Response:
        actions = Action.objects.filter(
            deleted=False,
            team=request.user.team_set.get()
        )
        matches = []
        for action in actions:
            events = Event.objects.filter_by_action(action)
            events = self._filter_request(request, events)
            for event in events[0: 20]:
                event.action = action
                matches.append(event)
        matches = sorted(matches, key=lambda event: event.id, reverse=True)
        matches = self._prefetch_events(matches[0: 20])
        return response.Response({'results': [self._serialize_actions(event) for event in matches]})

    @action(methods=['GET'], detail=False)
    def values(self, request: request.Request) -> response.Response:
        key = request.GET.get('key')
        params = [key, key]
        if request.GET.get('value'):
            where = " AND properties ->> %s LIKE %s"
            params.append(key)
            params.append('%{}%'.format(request.GET['value']))
        else:
            where = ''

        # This samples a bunch of events with that property, and then orders them by most popular in that sample
        # This is much quicker than trying to do this over the entire table
        values = Event.objects.raw("""
            SELECT
                value, COUNT(1) as id
            FROM ( 
                SELECT
                    ("posthog_event"."properties" -> %s) as "value"
                FROM
                    "posthog_event"
                WHERE ("posthog_event"."properties" -> %s) IS NOT NULL {} LIMIT 10000
            ) as "value"
            GROUP BY value
            ORDER BY id DESC
            LIMIT 50;
        """.format(where), params)

        return response.Response([{'name': value.value} for value in values])
