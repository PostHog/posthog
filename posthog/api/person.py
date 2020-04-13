from posthog.models import Event, Team, Person, PersonDistinctId, Cohort
from rest_framework import serializers, viewsets, response, request
from rest_framework.decorators import action
from django.db.models import Q, Prefetch, QuerySet, Subquery, OuterRef, Count, Func
from .event import EventSerializer
from typing import Union
from .base import CursorPagination as BaseCursorPagination

class PersonSerializer(serializers.HyperlinkedModelSerializer):
    last_event = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()

    class Meta:
        model = Person
        fields = ['id', 'name', 'distinct_ids', 'properties', 'last_event', 'created_at']

    def get_last_event(self, person: Person) -> Union[dict, None]:
        if not self.context['request'].GET.get('include_last_event'):
            return None
        last_event = Event.objects.filter(team_id=person.team_id, distinct_id__in=person.distinct_ids).order_by('-timestamp').first()
        if last_event:
            return {'timestamp': last_event.timestamp}
        else:
            return None

    def get_name(self, person: Person) -> str:
        if person.properties.get('email'):
            return person.properties['email']
        if len(person.distinct_ids) > 0:
            return person.distinct_ids[-1]
        return person.pk

class CursorPagination(BaseCursorPagination):
    ordering = '-id'
    page_size = 100

class PersonViewSet(viewsets.ModelViewSet):
    queryset = Person.objects.all()
    serializer_class = PersonSerializer
    pagination_class = CursorPagination

    def _filter_cohort(self, request: request.Request, queryset: QuerySet, team: Team) -> QuerySet:
        cohort = Cohort.objects.get(team=team, pk=request.GET['cohort'])
        queryset = queryset.filter(cohort.people_filter).order_by('id').distinct('id')
        return queryset

    def _filter_request(self, request: request.Request, queryset: QuerySet, team: Team) -> QuerySet:
        if request.GET.get('id'):
            people = request.GET['id'].split(',')
            queryset = queryset.filter(id__in=people)
        if request.GET.get('search'):
            parts = request.GET['search'].split(' ')
            contains = []
            for part in parts:
                if ':' in part:
                    queryset = queryset.filter(properties__has_key=part.split(':')[1])
                else:
                    contains.append(part)
            queryset = queryset.filter(properties__icontains=' '.join(contains))
        if request.GET.get('cohort'):
            queryset = self._filter_cohort(request, queryset, team)

        queryset = queryset.prefetch_related(Prefetch('persondistinctid_set', to_attr='distinct_ids_cache'))
        return queryset

    def destroy(self, request: request.Request, pk=None): # type: ignore
        team = request.user.team_set.get()
        person = Person.objects.get(team=team, pk=pk)
        events = Event.objects.filter(team=team, distinct_id__in=person.distinct_ids)
        events.delete()
        person.delete()
        return response.Response(status=204)

    def get_queryset(self):
        queryset = super().get_queryset()
        team = self.request.user.team_set.get()
        queryset = queryset.filter(team=team)
        return self._filter_request(self.request, queryset, team)

    @action(methods=['GET'], detail=False)
    def by_distinct_id(self, request):
        person = self.get_queryset().get(persondistinctid__distinct_id=str(request.GET['distinct_id']))
        return response.Response(PersonSerializer(person, context={'request': request}).data)

    @action(methods=['GET'], detail=False)
    def properties(self, request: request.Request) -> response.Response:
        class JsonKeys(Func):
            function = 'jsonb_object_keys'

        people = self.get_queryset()
        people = people\
            .annotate(keys=JsonKeys('properties'))\
            .values('keys')\
            .annotate(count=Count('id'))\
            .order_by('-count')

        return response.Response([{'name': event['keys'], 'count': event['count']} for event in people])

    @action(methods=['GET'], detail=False)
    def values(self, request: request.Request) -> response.Response:
        people = self.get_queryset()
        key = "properties__{}".format(request.GET.get('key'))
        people = people\
            .values(key)\
            .annotate(count=Count('id'))\
            .order_by('-count')

        if request.GET.get('value'):
            people = people.extra(where=["properties ->> %s LIKE %s"], params=[request.GET['key'], '%{}%'.format(request.GET['value'])])

        return response.Response([{'name': event[key], 'count': event['count']} for event in people[:50]])

