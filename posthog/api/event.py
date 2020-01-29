from posthog.models import Event, Team, Person, Element, Action, ActionStep, PersonDistinctId
from rest_framework import request, response, serializers, viewsets # type: ignore
from rest_framework.decorators import action # type: ignore
from django.http import HttpResponse, JsonResponse
from django.db.models import Q, Count, QuerySet, query, Prefetch, F
from django.forms.models import model_to_dict
from typing import Any, Union, Tuple, Dict, List
import re

class ElementSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Element
        fields = ['text', 'tag_name', 'href', 'attr_id', 'nth_child', 'nth_of_type', 'attributes', 'order']

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

    def _split_selector_into_parts(self, selector: str) -> Dict:
        data: Dict[str, Union[str, List]] = {}
        if 'id=' in selector:
            id_regex =  r"\[id=\'(.*)']"
            result = re.match(id_regex, selector)
            return {'attr_id': result[1]} # type: ignore
        if 'nth-child(' in selector:
            parts = selector.split(':nth-child(')
            data['nth_child'] = parts[1].replace(')', '')
            selector = parts[0]
        if '.' in selector:
            parts = selector.split('.')
            data['attr_class__contains'] = parts[1:]
            selector = parts[0]
        data['tag_name'] = selector
        return data

    def _event_matches_selector(self, event: Event, selector: str) -> bool:
        tags = selector.split(' > ')
        tags.reverse()

        prev = event.element_set.filter(**self._split_selector_into_parts(tags[0])).first()
        if not prev:
            return False
        for tag in tags[1:]:
            try:
                prev = event.element_set.get(order=prev.order + 1, **self._split_selector_into_parts(tag))
            except Element.DoesNotExist:
                return False
        return True

    def _element_matches_step(self, filters: Dict, element: Element) -> bool:
        match = True
        for key, value in filters.items():
            if key not in ['action', 'id'] and value:
                if getattr(element, key) != value:
                    match = False
        return match

    def _event_matches_step(self, event: Event, step: ActionStep) -> bool:
        filters = model_to_dict(step)
        # assume we have a match until we find a reason not to
        match = True
        if filters.get('url'):
            if event.properties['$current_url'] != filters['url']:
                return False
            filters.pop('url')
        elif event.element_set.count() == 0:
            # if the event doesn't have elements, it's a page view so should have matched url
            return False
        elif filters.get('selector'):
            if not self._event_matches_selector(event, filters['selector']):
                return False
            filters.pop('selector')
        # make sure at least one event matches 
        for element in event.element_set.all():
            if self._element_matches_step(filters, element):
                return True
        return False

    def _serialize_actions(self, event: Event, step: ActionStep) -> Dict:
        return {
            'id': "{}-{}".format(step.action_id, event.id),
            'event': EventSerializer(event).data,
            'action': {
                'name': step.action.name,
                'id': step.action_id
            }
        }

    @action(methods=['GET'], detail=False)
    def actions(self, request: request.Request) -> response.Response:
        events = self.get_queryset()
        events = self._filter_request(request, events)

        action_steps = ActionStep.objects.filter(action__team=request.user.team_set.get()).select_related('action')
        matches = []
        event_action_key: List[Tuple] = []
        count = 0
        for event in events:
            for step in action_steps:
                if (event.pk, step.action.pk) not in event_action_key:
                    if self._event_matches_step(event, step):
                        matches.append(self._serialize_actions(event, step))
                        event_action_key.append((event.pk, step.action.pk))
                        count += 1
            if count == 50:
                break
        return response.Response({'results': matches})