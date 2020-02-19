from posthog.models import Event, Team, Action, ActionStep, Element, User
from rest_framework import request, serializers, viewsets, authentication # type: ignore
from rest_framework.response import Response
from rest_framework.decorators import action # type: ignore
from rest_framework.exceptions import AuthenticationFailed
from django.db.models import Q, F, Count, Prefetch, functions, QuerySet
from django.forms.models import model_to_dict
from typing import Any, List, Dict
import pandas as pd # type: ignore
import numpy as np # type: ignore
import datetime
from dateutil.relativedelta import relativedelta


class ActionStepSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = ActionStep
        fields = ['id', 'event', 'tag_name', 'text', 'href', 'selector', 'url', 'name']

class ActionSerializer(serializers.HyperlinkedModelSerializer):
    steps = serializers.SerializerMethodField()

    class Meta:
        model = Action
        fields = ['id', 'name', 'steps', 'created_at', 'deleted']

    def get_steps(self, action: Action) -> List:
        steps = action.steps.all().order_by('id')
        return ActionStepSerializer(steps, many=True).data

class TemporaryTokenAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request: request.Request):
        # if the Origin is different, the only authentication method should be temporary_token
        # This happens when someone is trying to create actions from the editor on their own website
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
        if self.action == 'list':
            queryset = queryset.filter(deleted=False)

        if self.request.GET.get('actions'):
            queryset = queryset.filter(pk__in=self.request.GET['actions'].split(','))
        queryset = queryset.prefetch_related(Prefetch('steps', queryset=ActionStep.objects.order_by('id')))
        return queryset\
            .filter(team=self.request.user.team_set.get())\
            .order_by('-id')

    def create(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        action, created = Action.objects.get_or_create(
            name=request.data['name'],
            team=request.user.team_set.get(),
            deleted=False,
            defaults={
                'created_by': request.user
            }
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
        action = Action.objects.get(pk=kwargs['pk'], team=request.user.team_set.get())

        # If there's no steps property at all we just ignore it
        # If there is a step property but it's an empty array [], we'll delete all the steps
        if 'steps' in request.data:
            steps = request.data.pop('steps')
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

        serializer = ActionSerializer(action)
        serializer.update(action, request.data)
        return Response(ActionSerializer(action).data)

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        actions = self.get_queryset()
        actions_list = []
        for action in actions:
            events = Event.objects.filter_by_action(action)
            actions_list.append({
                'id': action.pk,
                'name': action.name,
                'count': events.count(),
                'steps': ActionStepSerializer(action.steps.all(), many=True).data
            })
        actions_list.sort(key=lambda action: action['count'], reverse=True)
        return Response({'results': actions_list})

    def _group_events_to_date(self, date_from, aggregates, steps, ):
        aggregates = pd.DataFrame([{'date': a['day'], 'count': a['count']} for a in aggregates])
        aggregates['date'] = aggregates['date'].dt.date
        # create all dates
        time_index = pd.date_range(date_from, periods=steps + 1, freq='D')
        grouped = pd.DataFrame(aggregates.groupby('date').mean(), index=time_index)

        # fill gaps
        grouped = grouped.fillna(0)
        return grouped

    def _filter_events(self, events: QuerySet, request: request.Request):
        for key, value in request.GET.items():
            if key != 'days' and key != 'actions' and key != 'display' and key != 'breakdown':
                events = events.filter(**{'properties__{}'.format(key): value})
        return events

    def _breakdown(self, events: QuerySet, breakdown_by: str) -> Dict:
        key = "properties__{}".format(breakdown_by)
        events = events\
            .values(key)\
            .annotate(count=Count('id'))\
            .order_by('-count')

        return [{'name': item[key] if item[key] else 'undefined', 'count': item['count']} for item in events]

    @action(methods=['GET'], detail=False)
    def trends(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        actions = self.get_queryset()
        actions = actions.filter(deleted=False)
        actions_list = []
        steps = int(request.GET.get('days', 7))
        date_from = datetime.date.today() - relativedelta(days=steps)
        date_to = datetime.date.today()
        for action in actions:
            append = {
                'action': {
                    'id': action.pk,
                    'name': action.name
                },
                'label': action.name,
                'count': 0,
                'breakdown': []
            }
            aggregates = self._filter_events(Event.objects.filter_by_action(action), request=request)\
                .filter(timestamp__gte=date_from)\
                .annotate(day=functions.TruncDay('timestamp'))\
                .values('day')\
                .annotate(count=Count('id'))\
                .order_by()

            if len(aggregates) > 0:
                dates_filled = self._group_events_to_date(date_from=date_from, aggregates=aggregates, steps=steps)
                values = [value[0] for key, value in dates_filled.iterrows()]
                append['labels'] = [key.strftime('%-d %B') for key, value in dates_filled.iterrows()]
                append['data'] = values
                append['count'] = sum(values)
            if request.GET.get('breakdown'):
                append['breakdown'] = self._breakdown(aggregates, breakdown_by=request.GET['breakdown'])
            actions_list.append(append)
        return Response(actions_list)