from posthog.models import Event, Team, Action, ActionStep, Element, User, Person
from posthog.utils import relative_date_parse, properties_to_Q
from rest_framework import request, serializers, viewsets, authentication # type: ignore
from rest_framework.response import Response

from rest_framework.decorators import action # type: ignore
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.utils.serializer_helpers import ReturnDict
from django.db.models import Q, F, Count, Prefetch, functions, QuerySet, TextField
from django.db import connection
from django.db.models.functions import Concat
from django.forms.models import model_to_dict
from django.utils.decorators import method_decorator
from django.utils.dateparse import parse_date
from typing import Any, List, Dict, Optional, Tuple
import pandas as pd # type: ignore
import numpy as np # type: ignore
import datetime
import json
from dateutil.relativedelta import relativedelta
from .person import PersonSerializer

class ActionStepSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = ActionStep
        fields = ['id', 'event', 'tag_name', 'text', 'href', 'selector', 'url', 'name', 'url_matching']


class ActionSerializer(serializers.HyperlinkedModelSerializer):
    steps = serializers.SerializerMethodField()
    count = serializers.SerializerMethodField()

    class Meta:
        model = Action
        fields = ['id', 'name', 'steps', 'created_at', 'deleted', 'count']

    def get_steps(self, action: Action):
        steps = action.steps.all().order_by('id')
        return ActionStepSerializer(steps, many=True).data

    def get_count(self, action: Action) -> Optional[int]:
        if self.context['request'].GET.get('include_count', False):
            return Event.objects.filter_by_action(action).count()
        return None

class TemporaryTokenAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request: request.Request):
        # if the Origin is different, the only authentication method should be temporary_token
        # This happens when someone is trying to create actions from the editor on their own website
        if request.headers.get('Origin') and request.headers['Origin'] not in request.build_absolute_uri('/'):
            if not request.GET.get('temporary_token'):
                raise AuthenticationFailed(detail="""No temporary_token set.
                    That means you're either trying to access this API from a different site,
                    or it means your proxy isn\'t sending the correct headers.
                    See https://github.com/PostHog/posthog/wiki/Running-behind-a-proxy for more information.
                    """)
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

    def _parse_actions(self, request: request.Request):
        if not self.request.GET.get('actions'):
            return None
        return json.loads(self.request.GET['actions'])

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == 'list':
            queryset = queryset.filter(deleted=False)

        if self.request.GET.get('actions'):
            queryset = queryset.filter(pk__in=[action['id'] for action in self._parse_actions(self.request.GET['actions'])])
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
                    **{key: value for key, value in step.items() if key not in ('isNew', 'selection')}
                )
        return Response(ActionSerializer(action, context={'request': request}).data)

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
                        **{key: value for key, value in step.items() if key not in ('isNew', 'selection')}
                    )

        serializer = ActionSerializer(action, context={'request': request})
        serializer.update(action, request.data)
        return Response(ActionSerializer(action, context={'request': request}).data)

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        actions = self.get_queryset()
        actions_list: List[Dict[Any, Any]] = ActionSerializer(actions, many=True, context={'request': request}).data # type: ignore
        if request.GET.get('include_count', False):
            actions_list.sort(key=lambda action: action.get('count', action['id']), reverse=True)
        return Response({'results': actions_list})

    def _group_events_to_date(self, date_from: datetime.date, date_to: datetime.date, aggregates):
        aggregates = pd.DataFrame([{'date': a['day'], 'count': a['count']} for a in aggregates])
        aggregates['date'] = aggregates['date'].dt.date
        # create all dates
        time_index = pd.date_range(date_from, date_to, freq='D')
        grouped = pd.DataFrame(aggregates.groupby('date').mean(), index=time_index)

        # fill gaps
        grouped = grouped.fillna(0)
        return grouped

    def _get_dates_from_request(self, request: request.Request) -> Tuple[datetime.date, datetime.date]:
        if request.GET.get('date_from'):
            date_from = relative_date_parse(request.GET['date_from'])
            if request.GET['date_from'] == 'all':
                date_from = None # type: ignore
        else:
            date_from = datetime.date.today() - relativedelta(days=7)

        if request.GET.get('date_to'):
            date_to = relative_date_parse(request.GET['date_to'])
        else:
            date_to = datetime.date.today()
        return date_from, date_to

    def _filter_events(self, request: request.Request) -> Q:
        filters = Q()
        date_from, date_to = self._get_dates_from_request(request=request)
        if date_from:
            filters &= Q(timestamp__gte=date_from)
        if date_to:
            filters &= Q(timestamp__lte=date_to + relativedelta(days=1))
        if not request.GET.get('properties'):
            return filters
        properties = json.loads(request.GET['properties'])
        filters &= properties_to_Q(properties)
        return filters

    def _breakdown(self, events: QuerySet, breakdown_by: str) -> List[Dict[str, int]]:
        key = "properties__{}".format(breakdown_by)
        events = events\
            .values(key)\
            .annotate(count=Count('id'))\
            .order_by('-count')

        return [{'name': item[key] if item[key] else 'undefined', 'count': item['count']} for item in events]

    def _append_data(self, append: Dict, dates_filled: pd.DataFrame) -> Dict:
        values = [value[0] for key, value in dates_filled.iterrows()]
        append['labels'] = [key.strftime('%a. %-d %B') for key, value in dates_filled.iterrows()]
        append['days'] = [key.strftime('%Y-%m-%d') for key, value in dates_filled.iterrows()]
        append['data'] = values
        append['count'] = sum(values)
        return append

    def _aggregate_by_day(self, action: Action, filters: Dict[Any, Any], request: request.Request):
        append: Dict[str, Any] = {}
        aggregates = Event.objects.filter_by_action(action)\
            .filter(self._filter_events(request))\
            .annotate(day=functions.TruncDay('timestamp'))\
            .values('day')\
            .annotate(count=Count('id'))\
            .order_by()

        if filters.get('math') == 'dau':
            aggregates = aggregates.annotate(count=Count('distinct_id', distinct=True))

        if len(aggregates) > 0:
            date_from, date_to = self._get_dates_from_request(request)
            if not date_from:
                date_from = aggregates[0]['day'].date()
            dates_filled = self._group_events_to_date(date_from=date_from, date_to=date_to, aggregates=aggregates)
            append = self._append_data(append, dates_filled)
        if request.GET.get('breakdown'):
            append['breakdown'] = self._breakdown(aggregates, breakdown_by=request.GET['breakdown'])

        return append

    def _execute_custom_sql(self, query, params):
        cursor = connection.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()

    def _stickiness(self, action: Action, filters: Dict[Any, Any], request: request.Request):
        date_from, date_to = self._get_dates_from_request(request)
        range_days = (date_to - date_from).days + 2

        events = Event.objects.filter_by_action(action, order_by=None)\
            .filter(self._filter_events(request))\
            .values('person_id') \
            .annotate(day_count=Count(functions.TruncDay('timestamp'), distinct=True))\
            .filter(day_count__lte=range_days)

        events_sql, events_sql_params = events.query.sql_with_params()
        aggregated_query = 'select count(v.person_id), v.day_count from ({}) as v group by v.day_count'.format(events_sql)
        aggregated_counts = self._execute_custom_sql(aggregated_query, events_sql_params)

        response: Dict[int, int] = {}
        for result in aggregated_counts:
            response[result[1]] = result[0]

        labels = []
        data = []

        for day in range(1, range_days):
            label = '{} day{}'.format(day, 's' if day > 1 else '')
            labels.append(label)
            data.append(response[day] if day in response else 0)

        return {
            'labels': labels,
            'days': [day for day in range(1, range_days)],
            'data': data
        }

    def _serialize_action(self, action: Action, filters: Dict[Any, Any], request: request.Request) -> Dict:
        append = {
            'action': {
                'id': action.pk,
                'name': action.name
            },
            'label': action.name,
            'count': 0,
            'breakdown': []
        }
        if request.GET.get('shown_as', 'Volume') == 'Volume':
            append.update(self._aggregate_by_day(action=action, filters=filters, request=request))
        elif request.GET['shown_as'] == 'Stickiness':
            append.update(self._stickiness(action=action, filters=filters, request=request))
        return append

    def _serialize_people(self, action: Action, people: QuerySet, request: request.Request) -> Dict:
        people_dict = [PersonSerializer(person, context={'request': request}).data for person in  people]
        return {
            'action': {
                'id': action.pk,
                'name': action.name
            },
            'people': people_dict,
            'count': len(people_dict)
        }

    @action(methods=['GET'], detail=False)
    def trends(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        actions = self.get_queryset()
        actions = actions.filter(deleted=False)
        actions_list = []

        parsed_actions = self._parse_actions(request)
        if parsed_actions:
            for filters in parsed_actions:
                db_action = [a for a in actions if a.id == filters['id']][0]
                actions_list.append(self._serialize_action(
                    action=db_action,
                    filters=filters,
                    request=request,
                ))
        else:
            for action in actions:
                actions_list.append(self._serialize_action(
                    action=action,
                    filters={},
                    request=request,
                ))
        return Response(actions_list)

    @action(methods=['GET'], detail=False)
    def people(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        actions = self.get_queryset()

        actions = actions.filter(deleted=False)
        actions_list = []

        for action in actions:
            events = Event.objects.filter_by_action(action, order_by=None).filter(self._filter_events(request))

            if request.GET.get('shown_as', 'Volume') == 'Volume':
                events = events.values('person_id').distinct()
            elif request.GET['shown_as'] == 'Stickiness':
                stickiness_days = int(request.GET['stickiness_days'])
                events = events\
                    .values('person_id')\
                    .annotate(day_count=Count(functions.TruncDay('timestamp'), distinct=True))\
                    .filter(day_count=stickiness_days)

            people = Person.objects\
                .filter(team=self.request.user.team_set.get(), id__in=[p['person_id'] for p in events[0:100]])

            actions_list.append(self._serialize_people(
                action=action,
                people=people,
                request=request
            ))

        return Response(actions_list)