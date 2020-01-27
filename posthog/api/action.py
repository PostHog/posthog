from posthog.models import Event, Team, Action, ActionStep, Element
from rest_framework import request, serializers, viewsets # type: ignore
from rest_framework.response import Response
from rest_framework.decorators import action # type: ignore
from django.db.models import Q, F
from django.forms.models import model_to_dict
from typing import Any


class ActionStepSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = ActionStep
        fields = ['id', 'tag_name', 'text', 'href', 'selector', 'url', 'name']

class ActionSerializer(serializers.HyperlinkedModelSerializer):
    steps = ActionStepSerializer(many=True, read_only=True)
    class Meta:
        model = Action
        fields = ['id', 'name', 'steps', 'created_at']


class ActionViewSet(viewsets.ModelViewSet):
    queryset = Action.objects.all()
    serializer_class = ActionSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset\
            .filter(team=self.request.user.team_set.get())\
            .order_by('-id')

    def create(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        if request.data.get('steps'):
            steps = request.data.pop('steps')
        action, created = Action.objects.get_or_create(
            name=request.data['name'],
            team=request.user.team_set.get()
        )
        if not created:
            return Response(data={'detail': 'event already exists'}, status=400)

        for step in steps:
            if step.get('isNew'):
                step.pop('isNew')
            ActionStep.objects.create(
                action=action,
                **step
            )
        return Response(ActionSerializer(action).data)

    def update(self, request: request.Request, pk: str, *args: Any, **kwargs: Any) -> Response:
        steps = request.data.pop('steps')
        action = Action.objects.get(pk=pk, team=request.user.team_set.get())
        serializer = ActionSerializer(action)
        serializer.update(action, request.data)

        # remove steps not in the request
        step_ids = [step['id'] for step in steps if step.get('id')]
        action.steps.exclude(pk__in=step_ids).delete()

        for step in steps:
            if step.get('id'):
                db_step = ActionStep.objects.get(pk=step['id'])
                serializer = ActionStepSerializer(db_step)
                serializer.update(db_step, step)
            else:
                if step.get('isNew'):
                    step.pop('isNew')
                ActionStep.objects.create(
                    action=action,
                    **step
                )
        return Response(ActionSerializer(action).data)




    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        actions = self.get_queryset()
        actions_list = []
        for action in actions:
            count = Event.objects.filter_by_action(action, count=True)
            actions_list.append({
                'id': action.pk,
                'name': action.name,
                'count': count
            })
        actions_list.sort(key=lambda action: action['count'], reverse=True)
        return Response({'results': actions_list})