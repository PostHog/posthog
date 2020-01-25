from posthog.models import Event, Team, Person
from rest_framework import request, response, serializers, viewsets # type: ignore
from rest_framework.decorators import action # type: ignore
from django.http import HttpResponse, JsonResponse
from django.db.models import Q
from typing import Any

class EventSerializer(serializers.HyperlinkedModelSerializer):
    person = serializers.SerializerMethodField()
    class Meta:
        model = Event
        fields = ['id', 'properties', 'elements', 'event', 'ip', 'timestamp', 'person']

    def get_person(self, event) -> Any:
        return hasattr(event, 'get') and event.get('person')

class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(team=self.request.user.team_set.get()).order_by('-timestamp')

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
            except KeyError:
                event['person'] = event['properties']['distinct_id']

        data = EventSerializer(queryset, many=True).data
        return response.Response({
            'results': data
        })