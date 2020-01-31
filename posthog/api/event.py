from posthog.models import Event, Team, Person, Element, Action, ActionStep, PersonDistinctId
from rest_framework import request, response, serializers, viewsets # type: ignore
from rest_framework.decorators import action # type: ignore
from django.http import HttpResponse, JsonResponse
from django.db.models import Q, Count, QuerySet, query, Prefetch, F
from django.forms.models import model_to_dict
from typing import Any, Union, Tuple, Dict, List
import re

class ElementSerializer(serializers.ModelSerializer):
    event = serializers.CharField() 
    class Meta:
        model = Element
        fields = ['event', 'text', 'tag_name', 'href', 'attr_id', 'nth_child', 'nth_of_type', 'attributes', 'order']

class EventSerializer(serializers.HyperlinkedModelSerializer):
    person = serializers.SerializerMethodField()
    elements = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = ['id', 'properties', 'elements', 'event', 'ip', 'timestamp', 'person']

    def get_person(self, event: Event) -> Any:
        if hasattr(event, 'person_properties'):
            return event.person_properties.get('$email', event.distinct_id)
        if hasattr(event, 'person'):
            return event.person.properties.get('$email', event.distinct_id)
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
            .prefetch_related('element_set')\
            .order_by('-timestamp')

    def _filter_by_action(self, request: request.Request) -> query.RawQuerySet:
            action = Action.objects.get(pk=request.GET['action_id'], team=request.user.team_set.get())
            where = None
            if request.GET.get('after'):
                where = ['posthog_event.timestamp >', request.GET['after']]
            return Event.objects.filter_by_action(action, limit=100, where=where)

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        for key, value in request.GET.items():
            if key == 'event' or key == 'ip':
                pass
            elif key == 'after':
                queryset = queryset.filter(timestamp__gt=request.GET['after'])
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
        if request.GET.get('action_id'):
            queryset: Union[QuerySet, query.RawQuerySet] = self._filter_by_action(request)
        else:
            queryset = self.get_queryset()
            queryset = self._filter_request(request, queryset)

        events = [EventSerializer(d).data for d in queryset[0: 100]]
        return response.Response({
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
        events = self.get_queryset()
        events = self._filter_request(request, events)

        action_steps = ActionStep.objects.filter(action__team=request.user.team_set.get()).select_related('action')
        matches = []
        count = 0
        for event in events:
            for action in event.actions:
                matches.append(self._serialize_actions(event, action))
                count += 1
            if count == 50:
                break
        return response.Response({'results': matches})