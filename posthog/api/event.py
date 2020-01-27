from posthog.models import Event, Team, Person, Element, Action
from rest_framework import request, response, serializers, viewsets # type: ignore
from rest_framework.decorators import action # type: ignore
from django.http import HttpResponse, JsonResponse
from django.db.models import Q, Count, QuerySet, query
from django.forms.models import model_to_dict
from typing import Any, Union

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

    def get_person(self, event) -> Any:
        return hasattr(event, 'get') and event.get('person')

    def get_elements(self, event):
        elements = Element.objects.filter(event_id=event.id)
        return ElementSerializer(elements, many=True).data

class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        return queryset\
            .filter(team=self.request.user.team_set.get())\
            .order_by('-timestamp')
            # .prefetch_related('elements')\

    def _filter_by_action(self, request: request.Request) -> query.RawQuerySet:
            action = Action.objects.get(pk=request.GET['action_id'], team=request.user.team_set.get())
            where = []
            if request.GET.get('after'):
                where.append(('posthog_event.timestamp >', request.GET['after']))
            return Event.objects.filter_by_action(action, limit=100, where=where)

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        for key, value in request.GET.items():
            if key == 'event' or key == 'ip':
                pass
            elif key == 'after':
                queryset = queryset.filter(timestamp__gt=request.GET['after'])
            elif key == 'person_id':
                person = Person.objects.get(pk=request.GET['person_id'])
                queryset = queryset.filter(properties__distinct_id__contained_by=person.distinct_ids)
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
        people = Person.objects.filter(distinct_ids__overlap=[v['properties']['distinct_id'] for v in events])
        for event in events:
            try:
                event['person'] = [person.properties['$email'] for person in people if event['properties']['distinct_id'] in person.distinct_ids][0]
            except (KeyError, IndexError):
                event['person'] = event['properties']['distinct_id']

        return response.Response({
            'results': events
        })

    @action(methods=['GET'], detail=False)
    def elements(self, request) -> response.Response:
        elements = Element.objects.filter(team=request.user.team_set.get())\
            .filter(tag_name__in=Element.USEFUL_ELEMENTS)\
            .values('tag_name', 'text', 'order')\
            .annotate(count=Count('event'))\
            .order_by('-count')
        
        return response.Response([{
            'name': '%s with text "%s"' % (el['tag_name'], el['text']),
            'count': el['count'],
            'common': el
        } for el in elements])