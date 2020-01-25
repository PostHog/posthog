from posthog.models import Event, Team, Person
from rest_framework import routers # type: ignore
from rest_framework import serializers, viewsets # type: ignore
from rest_framework.decorators import action # type: ignore
from django.http import HttpResponse, JsonResponse
from django.db.models import Q

class EventSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Event
        fields = ['id', 'properties', 'elements', 'event', 'ip', 'timestamp']


class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(team=self.request.user.team_set.get())

        for key, value in self.request.GET.items():
            if key != 'event' and key != 'ip':
                key = 'properties__%s' % key
            params = {}
            try:
                params[key] = int(value)
            except ValueError:
                params[key] = value
            queryset = queryset.filter(**params)
        return queryset.order_by('-id')

    @action(methods=['GET'], detail=False)
    def person(self, request) -> JsonResponse:
        people = Person.objects.filter(team=request.user.team_set.get())
        arr = []

        for person in people:
            last_event = Event.objects.filter(properties__distinct_id__in=person.distinct_ids).order_by('-timestamp').first()
            arr.append({
                "id": person.pk,
                "properties": person.properties,
                "is_user": person.is_user,
                "last_event": {
                    "event": last_event.event,
                    "timestamp": last_event.timestamp,
                } if last_event else {}
            })

        return JsonResponse(arr, safe=False)