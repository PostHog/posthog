from posthog.models import Event, Team, Action, ActionStep, Element, User
from rest_framework import request, serializers, viewsets, authentication # type: ignore
from rest_framework.response import Response
from rest_framework.decorators import action # type: ignore
from rest_framework.exceptions import AuthenticationFailed
from django.db.models import Q, F
from django.forms.models import model_to_dict
from typing import Any
import pandas as pd # type: ignore
import numpy as np # type: ignore
import datetime
from dateutil.relativedelta import relativedelta


class ActionStepSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = ActionStep
        fields = ['id', 'event', 'tag_name', 'text', 'href', 'selector', 'url', 'name']

class ActionSerializer(serializers.HyperlinkedModelSerializer):
    steps = ActionStepSerializer(many=True, read_only=True)
    class Meta:
        model = Action
        fields = ['id', 'name', 'steps', 'created_at',]

class TemporaryTokenAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request: request.Request):
        # if the Origin is different, the only authentication method should be temporary_token
        if request.headers.get('Origin') and request.headers['Origin'] not in request.build_absolute_uri('/'):
            if not request.GET.get('temporary_token'):
                raise AuthenticationFailed(detail='No token')
        if request.GET.get('temporary_token'):
            user = User.objects.filter(temporary_token=request.GET.get('temporary_token'))
            if not user.exists():
                raise AuthenticationFailed(detail='User doesnt exist')
            return (user.first(), None)
        return None

class ActionViewSet(viewsets.ModelViewSet):
    queryset = Action.objects.all()
    serializer_class = ActionSerializer
    authentication_classes = [TemporaryTokenAuthentication, authentication.SessionAuthentication, authentication.BasicAuthentication]

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset\
            .filter(team=self.request.user.team_set.get())\
            .order_by('-id')

    def create(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        action, created = Action.objects.get_or_create(
            name=request.data['name'],
            team=request.user.team_set.get(),
            created_by=request.user
        )
        if not created:
            return Response(data={'detail': 'action-exists', 'id': action.pk}, status=400)

        if request.data.get('steps'):
            for step in request.data['steps']:
                ActionStep.objects.create(
                    action=action,
                    **{key: value for key, value in step.items() if key != 'isNew' and key != 'selection'}
                )
        return Response(ActionSerializer(action).data)

    def update(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        steps = request.data.pop('steps')
        action = Action.objects.get(pk=kwargs['pk'], team=request.user.team_set.get())
        serializer = ActionSerializer(action)
        serializer.update(action, request.data)

        # remove steps not in the request
        step_ids = [step['id'] for step in steps if step.get('id')]
        action.steps.exclude(pk__in=step_ids).delete()

        for step in steps:
            if step.get('id'):
                db_step = ActionStep.objects.get(pk=step['id'])
                step_serializer = ActionStepSerializer(db_step)
                step_serializer.update(db_step, step)
            else:
                ActionStep.objects.create(
                    action=action,
                    **{key: value for key, value in step.items() if key != 'isNew' and key != 'selection'}
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

    def _group_events_to_date(self, date_from, aggregates, steps, ):
        aggregates = pd.DataFrame([{'date': a.day, 'count': a.id} for a in aggregates])
        aggregates['date'] = aggregates['date'].dt.date
        # create all dates
        time_index = pd.date_range(date_from, periods=steps + 1, freq='D')
        grouped = pd.DataFrame(aggregates.groupby('date').mean(), index=time_index)

        # fill gaps
        grouped = grouped.fillna(0)
        return grouped

    def _where_query(self, request: request.Request, date_from: datetime.date):
        ret = []
        for key, value in request.GET.items():
            if key != 'days':
                ret.append(['(posthog_event.properties -> %s) = %s', [key, '"{}"'.format(value)]])
        ret.append(['posthog_event.timestamp > %s', [date_from]])
        return ret

    @action(methods=['GET'], detail=False)
    def trends(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        actions = self.get_queryset()
        actions_list = []
        steps = int(request.GET.get('days', 7))
        date_from = datetime.date.today() - relativedelta(days=steps)
        date_to = datetime.date.today()
        for action in actions:
            aggregates = Event.objects.filter_by_action(action, count_by='day', where=self._where_query(request, date_from))
            if len(aggregates) == 0:
                continue
            dates_filled = self._group_events_to_date(date_from=date_from, aggregates=aggregates, steps=steps)
            values = [value[0] for key, value in dates_filled.iterrows()]
            actions_list.append({
                'action': {
                    'id': action.pk,
                    'name': action.name
                },
                'label': action.name,
                'labels': [key.strftime('%-d %B') for key, value in dates_filled.iterrows()],
                'data': values,
                'count': sum(values)
            })
        return Response(actions_list)