from posthog.models import Event, Team, Person, Element, Action, ActionStep, PersonDistinctId
from rest_framework import request, response, serializers, viewsets # type: ignore
from rest_framework.decorators import action # type: ignore
from django.http import HttpResponse, JsonResponse
from django.db.models import Q, Count, QuerySet, query, Prefetch, F, Func, TextField, functions
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
        elements = event.element_set.all()
        return ElementSerializer(elements, many=True).data

class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        return queryset\
            .filter(team=self.request.user.team_set.get())\
            .order_by('-timestamp')

    def _filter_by_action(self, request: request.Request) -> query.RawQuerySet:
            action = Action.objects.get(pk=request.GET['action_id'], team=request.user.team_set.get())
            where = None
            if request.GET.get('after'):
                where = [['posthog_event.timestamp > %s', [request.GET['after']]]]
            return Event.objects.filter_by_action(action, limit=101, where=where)

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        for key, value in request.GET.items():
            if key == 'event' or key == 'ip':
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
            else:
                key = 'properties__%s' % key
                params = {}
                params[key] = value
                queryset = queryset.filter(**params)
        return queryset

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        has_next = False
        if request.GET.get('action_id'):
            queryset: Union[QuerySet, query.RawQuerySet] = self._filter_by_action(request)
            has_next = len(queryset) > 100
        else:
            queryset = self.get_queryset().prefetch_related(Prefetch('element_set', queryset=Element.objects.order_by('order')))
            queryset = self._filter_request(request, queryset)
            has_next = queryset.count() > 100

        events = [EventSerializer(d).data for d in queryset[0: 100]]
        return response.Response({
            'next': has_next,
            'results': events
        })

    @action(methods=['GET'], detail=False)
    def elements(self, request) -> response.Response:
        elements = Element.objects.filter(event__team=request.user.team_set.get())\
            .filter(tag_name__in=Element.USEFUL_ELEMENTS)\
            .values('tag_name', 'text', 'order')\
            .annotate(count=Count('event'))\
            .order_by('-count')
        
        return response.Response([{
            'name': '%s with text "%s"' % (el['tag_name'], el['text']),
            'count': el['count'],
            'common': el
        } for el in elements])

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
        actions = Action.objects.filter(team=request.user.team_set.get()).prefetch_related(Prefetch('steps', queryset=ActionStep.objects.all()))
        matches = []
        for action in actions:
            events = Event.objects.filter_by_action(action, limit=20)
            for event in events:
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