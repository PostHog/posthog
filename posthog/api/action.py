from posthog.models import Event, Team, Action, ActionStep, Element, User, Person, Filter, Entity
from posthog.utils import relative_date_parse, properties_to_Q
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from rest_framework import request, serializers, viewsets, authentication
from rest_framework.response import Response

from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.utils.serializer_helpers import ReturnDict
from django.db.models import Q, F, Count, Prefetch, functions, QuerySet, TextField
from django.db import connection
from django.db.models.functions import Concat
from django.forms.models import model_to_dict
from django.utils.decorators import method_decorator
from django.utils.dateparse import parse_date
from typing import Any, List, Dict, Optional, Tuple
import pandas as pd
import numpy as np
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
        fields = ['id', 'name', 'post_to_slack', 'steps', 'created_at', 'deleted', 'count']

    def get_steps(self, action: Action):
        steps = action.steps.all()
        return ActionStepSerializer(steps, many=True).data

    def get_count(self, action: Action) -> Optional[int]:
        if hasattr(action, 'count'):
            return action.count  # type: ignore
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

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == 'list':  # type: ignore
            queryset = queryset.filter(deleted=False)

        if self.request.GET.get(TREND_FILTER_TYPE_ACTIONS):
            queryset = queryset.filter(pk__in=[action.id for action in Filter({'actions': json.loads(self.request.GET['actions'])}).actions])

        if self.request.GET.get('include_count'):
            queryset = queryset.annotate(count=Count(TREND_FILTER_TYPE_EVENTS))

        queryset = queryset.prefetch_related(Prefetch('steps', queryset=ActionStep.objects.order_by('id')))
        return queryset\
            .filter(team=self.request.user.team_set.get())\
            .order_by('-id')

    def create(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        action, created = Action.objects.get_or_create(
            name=request.data['name'],
            post_to_slack=request.data.get('post_to_slack', False),
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
        action.calculate_events()
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
        action.calculate_events()
        return Response(ActionSerializer(action, context={'request': request}).data)

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        actions = self.get_queryset()
        actions_list: List[Dict[Any, Any]] = ActionSerializer(actions, many=True, context={'request': request}).data # type: ignore
        if request.GET.get('include_count', False):
            actions_list.sort(key=lambda action: action.get('count', action['id']), reverse=True)
        return Response({'results': actions_list})

    def _group_events_to_date(self, date_from: datetime.datetime, date_to: datetime.datetime, aggregates: QuerySet, interval:str) -> Dict[datetime.datetime, int]:
        freq_map = {
            'minute': '60S',
            'hour': 'H',
            'day': 'D',
            'week': 'W',
            'month': 'M'
        }
        # handle "today" date range
        if date_from == date_to:
            date_from = pd.Timestamp(ts_input=date_from).replace(hour=0)
            date_to = pd.Timestamp(ts_input=date_to).replace(hour=23)

        time_index = pd.date_range(date_from, date_to, freq=freq_map[interval])
        if len(aggregates) > 0:
            dataframe = pd.DataFrame([{'date': a[interval], 'count': a['count']} for a in aggregates])
            if interval == 'week':
                dataframe['date'] = dataframe['date'].apply(lambda x: x - pd.offsets.Week(weekday=6))
            elif interval == 'month':
                dataframe['date'] = dataframe['date'].apply(lambda x: x - pd.offsets.MonthEnd(n=1))
            dataframe = pd.DataFrame(dataframe.groupby('date').mean(), index=time_index)
        else:
            dataframe = pd.DataFrame([], index=time_index)

        # fill gaps
        dataframe = dataframe.fillna(0)
        return {key: value[0] if len(value) > 0 else 0 for key, value in dataframe.iterrows()}

    def _filter_events(self, filter: Filter) -> Q:
        filters = Q()
        if filter.date_from:
            filters &= Q(timestamp__gte=filter.date_from)
        if filter.date_to:
            relativity = relativedelta(days=1)
            if filter.interval == 'hour':
                relativity = relativedelta(hours=1)
            elif filter.interval == 'minute':
                relativity = relativedelta(minutes=1)
            elif filter.interval == 'week':
                relativity = relativedelta(weeks=1)
            elif filter.interval == 'month':
                relativity = relativedelta(months=1) - relativity # go to last day of month instead of first of next
            filters &= Q(timestamp__lte=filter.date_to + relativity)
        if filter.properties:
            filters &= properties_to_Q(filter.properties)
        return filters

    def _breakdown(self, append: Dict, filtered_events: QuerySet, entity: Entity, filter: Filter, breakdown_by: str) -> Dict:
        key = "properties__{}".format(breakdown_by)
        events = filtered_events\
            .filter(self._filter_events(filter))\
            .values(key)\
            .annotate(count=Count(1))\
            .order_by('-count')

        events = self._process_math(events, entity)

        values = [{'name': item[key] if item[key] else 'undefined', 'count': item['count']} for item in events]
        append['breakdown'] = values
        append['count'] = sum(item['count'] for item in values)
        return append

    def _append_data(self, append: Dict, dates_filled: pd.DataFrame, interval: str) -> Dict:
        append['data'] = []
        append['labels'] = []
        append['days'] = []

        labels_format = '%a. %-d %B'
        days_format = '%Y-%m-%d'

        if interval == 'hour' or interval == 'minute':
            labels_format += ', %H:%M'
            days_format += ' %H:%M:%S'

        for date, value in dates_filled.items():
            append['days'].append(date.strftime(days_format))
            append['labels'].append(date.strftime(labels_format))
            append['data'].append(value)

        append['count'] = sum(append['data'])
        return append

    def _get_interval_annotation(self, key: str) -> Dict[str, Any]:
        map: Dict[str, Any] = {
            'minute': functions.TruncMinute('timestamp'),
            'hour': functions.TruncHour('timestamp'),
            'day': functions.TruncDay('timestamp'),
            'week': functions.TruncWeek('timestamp'),
            'month': functions.TruncMonth('timestamp'),
        }
        func = map.get(key)
        if func is None:
            return {'day': map.get('day')} # default

        return { key: func }

    def _aggregate_by_interval(self, filtered_events: QuerySet, entity: Entity, filter: Filter, interval: str, request: request.Request) -> Dict[str, Any]:
        append: Dict[str, Any] = {}
        interval_annotation = self._get_interval_annotation(interval)
        aggregates = filtered_events\
            .filter(self._filter_events(filter))\
            .annotate(**interval_annotation)\
            .values(interval)\
            .annotate(count=Count(1))\
            .order_by()

        aggregates = self._process_math(aggregates, entity)

        dates_filled = self._group_events_to_date(
            date_from=filter.date_from if filter.date_from else pd.Timestamp(aggregates[0][interval]),
            date_to=filter.date_to,
            aggregates=aggregates,
            interval=interval
        )
        append = self._append_data(append, dates_filled, interval)
        if request.GET.get('breakdown'):
            append = self._breakdown(append=append, filtered_events=filtered_events, entity=entity, filter=filter, breakdown_by=request.GET['breakdown'])

        return append

    def _process_math(self, query: QuerySet, entity: Entity):
        if entity.math == 'dau':
            query = query.annotate(count=Count('distinct_id', distinct=True))
        return query

    def _execute_custom_sql(self, query, params):
        cursor = connection.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()

    def _stickiness(self, filtered_events: QuerySet, filter: Filter) -> Dict[str, Any]:
        range_days = (filter.date_to - filter.date_from).days + 2 if filter.date_from else 90

        events = filtered_events\
            .filter(self._filter_events(filter))\
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
            'data': data,
            'count': sum(data)
        }

    def _serialize_entity(self, entity: Entity, filter: Filter, request: request.Request, team: Team) -> Dict:
        interval = request.GET.get('interval')
        if interval is None:
            interval = 'day'

        serialized: Dict[str, Any] = {
            'action': {
                'id': entity.id,
                'name': entity.name,
                'type': entity.type
            },
            'label': entity.name,
            'count': 0,
            'breakdown': [],
            'data': [],
            'labels': [],
            'days': []
        }

        if request.GET.get('shown_as', 'Volume') == 'Volume':
            filtered_events = self._process_entity_for_events(entity=entity, team=team)
            serialized.update(self._aggregate_by_interval(filtered_events=filtered_events, entity=entity, filter=filter, interval=interval, request=request))
        elif request.GET['shown_as'] == 'Stickiness':
            filtered_events = self._process_entity_for_events(entity, team=team, order_by=None)
            serialized.update(self._stickiness(filtered_events=filtered_events, filter=filter))
        return serialized

    def _serialize_people(self, entity: Entity, people: QuerySet, request: request.Request) -> Dict:
        people_dict = [PersonSerializer(person, context={'request': request}).data for person in  people]
        return {
            'action': {
                'id': entity.id,
                'name': entity.name
            },
            'people': people_dict,
            'count': len(people_dict)
        }

    def _process_entity_for_events(self, entity: Entity, team: Team, order_by="-id") -> QuerySet:
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            events = Event.objects.filter(action__pk=entity.id).add_person_id(team.pk)
            if order_by:
                events = events.order_by(order_by)
            return events
        elif entity.type == TREND_FILTER_TYPE_EVENTS:
            return Event.objects.filter_by_event_with_people(event=entity.id, team_id=team.pk, order_by=order_by)
        return QuerySet()

    @action(methods=['GET'], detail=False)
    def trends(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        actions = self.get_queryset()
        actions = actions.filter(deleted=False)
        team = request.user.team_set.get()
        entities_list = []
        filter = Filter(request=request)

        if len(filter.entities) == 0:
            filter.entities = [Entity({'id': action.id, 'name': action.name, 'type': TREND_FILTER_TYPE_ACTIONS}) for action in actions]

        for entity in filter.entities:
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                try:
                    db_action = [action for action in actions if action.id == entity.id][0]
                    entity.name = db_action.name
                except IndexError:
                    continue
            trend_entity = self._serialize_entity(
                entity=entity,
                filter=filter,
                request=request,
                team=team
            )
            entities_list.append(trend_entity)
        return Response(entities_list)

    @action(methods=['GET'], detail=False)
    def people(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        team = request.user.team_set.get()
        entity = Entity({
            'id': request.GET['entityId'],
            'type': request.GET['type']
        })
        filter = Filter(request=request)

        def _calculate_people(entity: Entity, events: QuerySet):
            if request.GET.get('shown_as', 'Volume') == 'Volume':
                events = events.values('person_id').distinct()
            elif request.GET['shown_as'] == 'Stickiness':
                stickiness_days = int(request.GET['stickiness_days'])
                events = events\
                    .values('person_id')\
                    .annotate(day_count=Count(functions.TruncDay('timestamp'), distinct=True))\
                    .filter(day_count=stickiness_days)

            people = Person.objects\
                .filter(team=team, id__in=[p['person_id'] for p in events[0:100]])

            return self._serialize_people(
                entity=entity,
                people=people,
                request=request
            )

        if entity.type == TREND_FILTER_TYPE_EVENTS:
            filtered_events =  self._process_entity_for_events(entity, team=team, order_by=None)\
                .filter(self._filter_events(filter))
            people = _calculate_people(entity=entity, events=filtered_events)
            return Response([people])
        elif entity.type == TREND_FILTER_TYPE_ACTIONS:
            actions = super().get_queryset()
            actions = actions.filter(deleted=False)
            try:
                action = actions.get(pk=entity.id)
            except Action.DoesNotExist:
                return Response([])
            filtered_events = self._process_entity_for_events(entity, team=team, order_by=None).filter(self._filter_events(filter))
            people = _calculate_people(entity=entity, events=filtered_events)
            return Response([people])

        return Response([])
