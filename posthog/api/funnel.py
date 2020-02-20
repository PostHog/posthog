from posthog.models import Funnel, FunnelStep, Action, ActionStep, Event, Funnel, Person
from rest_framework import request, response, serializers, viewsets # type: ignore
from rest_framework.decorators import action # type: ignore
from django.db.models import QuerySet, query, Model
from typing import List, Dict, Any


class FunnelSerializer(serializers.HyperlinkedModelSerializer):
    steps = serializers.SerializerMethodField()

    class Meta:
        model = Funnel
        fields = ['id', 'name', 'deleted', 'steps']

    def _order_people_in_step(self, steps: List[Dict[str, Any]], people: List[int]) -> List[int]:
        def order(person):
            score = 0
            for step in steps:
                if person in step['people']:
                    score += 1
            return (score, person)
        return sorted(people, key=order, reverse=True)

    def get_steps(self, funnel: Funnel) -> List[Dict[str, Any]]:
        steps = []
        people = None
        db_steps = funnel.steps.all().order_by('order', 'id')
        for step in db_steps:
            count = 0
            if people == None or len(people) > 0: # type: ignore
                people = Event.objects.filter_by_action(
                    step.action,
                    where='({})' .format(') OR ('.join([
                        "posthog_event.id > {} AND posthog_persondistinctid.person_id = {}".format(person.event_id, person.id)
                        for person in people # type: ignore
                    ])) if people else None,
                    group_by='person_id',
                    group_by_table='posthog_persondistinctid')
                if len(people) > 0:
                    count = len(people)
            steps.append({
                'id': step.id,
                'action_id': step.action.id,
                'name': step.action.name,
                'order': step.order,
                'people': [person.id for person in people] if people else [],
                'count':  count
            })
        if len(steps) > 0:
            steps[0]['people'] = self._order_people_in_step(steps, steps[0]['people'])
        return steps

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Funnel:
        request = self.context['request']
        funnel = Funnel.objects.create(team=request.user.team_set.get(), **validated_data)
        if request.data.get('steps'):
            for index, step in enumerate(request.data['steps']):
                if step.get('action_id'):
                    FunnelStep.objects.create(
                        funnel=funnel,
                        action_id=step['action_id'],
                        order=index
                    )
        return funnel

    def update(self, funnel: Funnel, validated_data: Any) -> Funnel: # type: ignore
        request = self.context['request']

        funnel.deleted = validated_data.get('deleted', funnel.deleted)
        funnel.name = validated_data.get('name', funnel.name)
        funnel.save()

        # If there's no steps property at all we just ignore it
        # If there is a step property but it's an empty array [], we'll delete all the steps
        if 'steps' in request.data:
            steps = request.data.pop('steps')

            steps_to_delete = funnel.steps.exclude(pk__in=[step.get('id') for step in steps if step.get('id') and '-' not in str(step['id'])])
            steps_to_delete.delete()
            for index, step in enumerate(steps):
                if step.get('action_id'):
                    # make sure it's not a uuid, in which case we can just ignore id
                    if step.get('id') and '-' not in str(step['id']):
                        db_step = FunnelStep.objects.get(funnel=funnel, pk=step['id'])
                        db_step.action_id = step['action_id']
                        db_step.order = index
                        db_step.save()
                    else:
                        FunnelStep.objects.create(
                            funnel=funnel,
                            order=index,
                            action_id=step['action_id']
                        )
        return funnel

class FunnelViewSet(viewsets.ModelViewSet):
    queryset = Funnel.objects.all()
    serializer_class = FunnelSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == 'list': # type: ignore
            queryset = queryset.filter(deleted=False)
        return queryset\
            .filter(team=self.request.user.team_set.get())