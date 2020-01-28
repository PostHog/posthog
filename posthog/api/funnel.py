from posthog.models import Funnel, FunnelStep, Action, ActionStep, Event, Funnel, Person
from rest_framework import request, response, serializers, viewsets # type: ignore
from rest_framework.decorators import action # type: ignore
from django.db.models import QuerySet, query
from typing import List, Dict, Any


class FunnelSerializer(serializers.HyperlinkedModelSerializer):
    steps = serializers.SerializerMethodField()

    class Meta:
        model = Funnel
        fields = ['id', 'name', 'steps']

    def get_steps(self, funnel: Funnel) -> List[Dict[str, Any]]:
        steps = []
        people = None
        db_steps = funnel.steps.all().order_by('order', 'id')
        for step in db_steps:
            count = 0
            people = Event.objects.filter_by_action(
                step.action,
                where=' OR '.join([
                    "posthog_event.id > {} AND posthog_persondistinctid.person_id = {}".format(person.event_id, person.id)
                    for person in people # type: ignore
                ]) if people else None,
                group_by='person_id',
                group_by_table='posthog_persondistinctid')
            if len(people) > 0:
                count = len(people)
            steps.append({
                'id': step.id,
                'action_id': step.action.id,
                'name': step.action.name,
                'people': [person.id for person in people],
                'count':  count
            })
        return steps

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Funnel:
        request = self.context['request']
        steps = request.data.pop('steps')
        funnel = Funnel.objects.create(team=request.user.team_set.get(), **validated_data)
        for index, step in enumerate(steps):
            FunnelStep.objects.create(
                funnel=funnel,
                action_id=step['action'],
                order=index
            )
        return funnel

class FunnelViewSet(viewsets.ModelViewSet):
    queryset = Funnel.objects.all()
    serializer_class = FunnelSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        return queryset\
            .filter(team=self.request.user.team_set.get())\
 