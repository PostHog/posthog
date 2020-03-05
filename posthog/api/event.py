from posthog.models import Event, Team, Person, Element, Action, PersonDistinctId, ElementGroup
from rest_framework import request, response, serializers, viewsets # type: ignore
from rest_framework.decorators import action # type: ignore
from django.http import HttpResponse, JsonResponse
from django.db.models import Q, Count, QuerySet, query, F, Func, functions
from django.forms.models import model_to_dict
from typing import Any, Union, Tuple, Dict, List
import re

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
        fields = ['id', 'distinct_id', 'properties', 'elements', 'event', 'ip', 'timestamp', 'person']

    def get_person(self, event: Event) -> Any:
        if hasattr(event, 'person_properties'):
            return event.person_properties.get('email', event.distinct_id) # type: ignore
        try:
            return event.person.properties.get('email', event.distinct_id)
        except:
            return event.distinct_id

    def get_elements(self, event):
        if not event.elements_hash:
            return []
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
            if key in ('event', 'ip'):
                pass
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
                queryset = queryset.filter_by_action(Action.objects.get(pk=value))
            else:
                key = 'properties__%s' % key
                params = {}
                params[key] = value
                queryset = queryset.filter(**params)
        return queryset

    def _serialize_actions(self, event: Event, action: Action) -> Dict:
        return {
            'id': "{}-{}".format(action.pk, event.id),
            'event': EventSerializer(event).data,
            'action': {
                'name': action.name,
                'id': action.pk
            }
        }

    @action(methods=['GET'], detail=False)
    def actions(self, request: request.Request) -> response.Response:
        actions = Action.objects.filter(
            deleted=False,
            team=request.user.team_set.get()
        )
        matches = []
        for action in actions:
            events = Event.objects.filter_by_action(action)
            for event in events[0: 20]:
                matches.append({'event': event, 'action': action})
        matches = sorted(matches, key=lambda match: match['event'].id, reverse=True)
        return response.Response({'results': [self._serialize_actions(match['event'], match['action']) for match in matches[0: 20]]})

    @action(methods=['GET'], detail=False)
    def names(self, request: request.Request) -> response.Response:
        events = self.get_queryset()
        events = events\
            .values('event')\
            .annotate(count=Count('id'))\
            .order_by('-count')

        return response.Response([{'name': event['event'], 'count': event['count']} for event in events])

    @action(methods=['GET'], detail=False)
    def properties(self, request: request.Request) -> response.Response:
        class JsonKeys(Func):
            function = 'jsonb_object_keys'

        events = self.get_queryset()
        events = events\
            .annotate(keys=JsonKeys('properties'))\
            .values('keys')\
            .annotate(count=Count('id'))\
            .order_by('-count')

        return response.Response([{'name': event['keys'], 'count': event['count']} for event in events])

    @action(methods=['GET'], detail=False)
    def values(self, request: request.Request) -> response.Response:
        events = self.get_queryset()
        key = "properties__{}".format(request.GET.get('key'))
        events = events\
            .values(key)\
            .annotate(count=Count('id'))\
            .order_by('-count')

        if request.GET.get('value'):
            events = events.extra(where=["properties ->> %s LIKE %s"], params=[request.GET['key'], '%{}%'.format(request.GET['value'])])

        return response.Response([{'name': event[key], 'count': event['count']} for event in events[:50]])
