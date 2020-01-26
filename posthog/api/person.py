from posthog.models import Event, Team, Person
from rest_framework import serializers, viewsets, response
from rest_framework.decorators import action
from django.db.models import Q
from .event import EventSerializer
from typing import Union

class PersonSerializer(serializers.HyperlinkedModelSerializer):
    last_event = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()

    class Meta:
        model = Person
        fields = ['id', 'name', 'distinct_ids', 'properties', 'last_event']

    def get_last_event(self, person: Person) -> Union[dict, None]:
        last_event = Event.objects.filter(properties__distinct_id__contained_by=person.distinct_ids).order_by('-timestamp').first()
        if last_event:
            return EventSerializer(last_event).data
        else:
            return None

    def get_name(self, person: Person) -> str:
        if person.properties.get('$email'):
            return person.properties['$email']
        if len(person.distinct_ids) > 0:
            return person.distinct_ids[-1]
        return person.pk

class PersonViewSet(viewsets.ModelViewSet):
    queryset = Person.objects.all()
    serializer_class = PersonSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(team=self.request.user.team_set.get())
        return queryset.order_by('-id')

    @action(methods=['GET'], detail=False)
    def by_distinct_id(self, request):
        # sometimes race condition creates 2
        person = self.get_queryset().filter(distinct_ids__contains=[request.GET['distinct_id']]).first()
        
        return response.Response(PersonSerializer(person).data)

