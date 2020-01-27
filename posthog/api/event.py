from posthog.models import Event, Team, Person, Element
from rest_framework import request, response, serializers, viewsets # type: ignore
from rest_framework.decorators import action # type: ignore
from django.http import HttpResponse, JsonResponse
from django.db.models import Q, Count
from typing import Any

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
        elements = Element.objects.filter(event_id=event['id'])
        return ElementSerializer(elements, many=True).data

class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset\
            .filter(team=self.request.user.team_set.get())\
            .prefetch_related('elements')\
            .order_by('-timestamp')

    def _filter_request(self, request, queryset):
        for key, value in self.request.GET.items():
            if key == 'event' or key == 'ip':
                pass
            elif key == 'after':
                queryset = queryset.filter(timestamp__gt=self.request.GET['after'])
            elif key == 'person_id':
                person = Person.objects.get(pk=self.request.GET['person_id'])
                queryset = queryset.filter(properties__distinct_id__contained_by=person.distinct_ids)
            else:
                key = 'properties__%s' % key
                params = {}
                params[key] = value
                queryset = queryset.filter(**params)
        return queryset

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        queryset = self.get_queryset()
        queryset = self._filter_request(request, queryset)
        queryset = queryset[0:100]
        people = Person.objects.filter(distinct_ids__overlap=[v['properties__distinct_id'] for v in queryset.values('properties__distinct_id')])
        queryset = [d for d in queryset.values()]

        for event in queryset:
            try:
                event['person'] = [person.properties['$email'] for person in people if event['properties']['distinct_id'] in person.distinct_ids][0]
            except (KeyError, IndexError):
                event['person'] = event['properties']['distinct_id']

        data = EventSerializer(queryset, many=True).data
        return response.Response({
            'results': data
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