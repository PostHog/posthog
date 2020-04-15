from django.db import models, connection
from django.db.models import Exists, OuterRef, Q, Subquery, F, signals, Prefetch, QuerySet
from django.dispatch import receiver
from django.contrib.postgres.fields import JSONField, ArrayField
from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils.translation import ugettext_lazy as _
from django.utils.timezone import now
from django.dispatch import receiver
from django.forms.models import model_to_dict
from django.utils import timezone
from posthog.utils import properties_to_Q, request_to_date_query
from posthog.tasks.slack import post_event_to_slack
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from typing import List, Tuple, Optional, Any, Union, Dict
from django.db import transaction
from sentry_sdk import capture_exception
from dateutil.relativedelta import relativedelta

import secrets
import re
import json
import hashlib
import uuid
import random
import datetime

attribute_regex = r"([a-zA-Z]*)\[(.*)=[\'|\"](.*)[\'|\"]\]"

def split_selector_into_parts(selector: str) -> List:
    tags = selector.split(' > ')
    tags.reverse()
    ret: List[Dict[str, Union[str, List]]] = []
    for tag in tags:
        data: Dict[str, Union[str, List]] = {}
        if '[id=' in tag:
            result = re.search(attribute_regex, tag)
            data['attr_id'] = result[3] # type: ignore
            tag = result[1] # type: ignore
        if '[' in tag:
            result = re.search(attribute_regex, tag)
            data['attributes__{}'.format(result[2])] = result[3] # type: ignore
            tag = result[1] # type: ignore
        if 'nth-child(' in tag:
            parts = tag.split(':nth-child(')
            data['nth_child'] = parts[1].replace(')', '')
            tag = parts[0]
        if '.' in tag:
            parts = tag.split('.')
            data['attr_class'] = parts[1:]
            tag = parts[0]
        if tag:
            data['tag_name'] = tag
        ret.append(data)
    return ret


def is_email_restricted_from_signup(email: str) -> bool:
    if not hasattr(settings, 'RESTRICT_SIGNUPS'):
        return False

    restricted_signups: Union[str, bool] = settings.RESTRICT_SIGNUPS
    if restricted_signups is False:
        return False

    domain = email.rsplit('@', 1)[1]
    whitelisted_domains = str(settings.RESTRICT_SIGNUPS).split(',')
    if domain in whitelisted_domains:
        return False

    return True


class UserManager(BaseUserManager):
    """Define a model manager for User model with no username field."""

    use_in_migrations = True

    def _create_user(self, email: Optional[str], password: str, **extra_fields):
        """Create and save a User with the given email and password."""
        if email is None:
            raise ValueError('The given email must be set')

        email = self.normalize_email(email)
        if is_email_restricted_from_signup(email):
            raise ValueError("Can't sign up with this email")

        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save()
        return user

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a regular User with the given email and password."""
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        if not settings.TEST:
            extra_fields.setdefault('distinct_id', secrets.token_urlsafe(32))
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        """Create and save a SuperUser with the given email and password."""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self._create_user(email, password, **extra_fields)

class User(AbstractUser):
    username = None # type: ignore
    email = models.EmailField(_('email address'), unique=True)
    temporary_token: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    distinct_id: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    email_opt_in: models.BooleanField = models.BooleanField(default=False, null=False, blank=False)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS: List[str] = []

    objects: UserManager = UserManager() # type: ignore


class TeamManager(models.Manager):

    def create_with_data(self, users: Optional[List[User]], **kwargs):
        kwargs['api_token'] = kwargs.get('api_token', secrets.token_urlsafe(32))
        kwargs['signup_token'] = kwargs.get('signup_token', secrets.token_urlsafe(22))
        team = Team.objects.create(**kwargs)
        if users:
            team.users.set(users)

        action = Action.objects.create(team=team, name='Pageviews')
        ActionStep.objects.create(action=action, event='$pageview')

        DashboardItem.objects.create(team=team, name='Pageviews this week', type='ActionsLineGraph', filters={TREND_FILTER_TYPE_ACTIONS: [{'id': action.pk, 'type': TREND_FILTER_TYPE_ACTIONS}]})
        DashboardItem.objects.create(
            team=team,
            name='Most popular browsers this week',
            type='ActionsTable',
            filters={TREND_FILTER_TYPE_ACTIONS: [{'id': action.pk, 'type': TREND_FILTER_TYPE_ACTIONS}], 'display': 'ActionsTable', 'breakdown': '$browser'}
        )
        DashboardItem.objects.create(team=team, name='Daily Active Users', type='ActionsLineGraph', filters={TREND_FILTER_TYPE_ACTIONS: [{'id': action.pk, 'math': 'dau', 'type': TREND_FILTER_TYPE_ACTIONS}]})
        return team

class Team(models.Model):
    users: models.ManyToManyField = models.ManyToManyField(User, blank=True)
    api_token: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    signup_token: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    app_urls: ArrayField = ArrayField(models.CharField(max_length=200, null=True, blank=True), default=list)
    name: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    opt_out_capture: models.BooleanField = models.BooleanField(default=False)
    slack_incoming_webhook: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    event_names: JSONField = JSONField(default=list)
    event_properties: JSONField = JSONField(default=list)

    objects = TeamManager()

    def __str__(self):
        if self.name:
            return self.name
        if self.app_urls and self.app_urls[0]:
            return self.app_urls.join(', ')
        return str(self.pk)

class EventManager(models.QuerySet):
    def filter_by_element(self, action_step):
        groups = ElementGroup.objects.filter(team=action_step.action.team_id)
        filter = {}
        for key in ['tag_name', 'text', 'href']:
            if getattr(action_step, key):
                filter['element__{}'.format(key)] = getattr(action_step, key)

        if action_step.selector:
            parts = split_selector_into_parts(action_step.selector)
            subqueries = {}
            for index, tag in enumerate(parts):
                if tag.get('attr_class'):
                    attr_class = tag.pop('attr_class')
                    tag['attr_class__contains'] = attr_class
                subqueries['match_{}'.format(index)] = Subquery(
                    Element.objects.filter(group_id=OuterRef('pk'), **tag).values('order')[:1]
                )
            groups = groups.annotate(**subqueries)  # type: ignore
            for index, _ in enumerate(parts):
                filter['match_{}__isnull'.format(index)] = False
                if index > 0:
                    filter['match_{}__gt'.format(index)] = F('match_{}'.format(index-1)) # make sure the ordering of the elements is correct

        if not filter:
            return {}
        groups = groups.filter(**filter)
        return {'elements_hash__in': groups.values_list('hash', flat=True)}

    def filter_by_url(self, action_step):
        if not action_step.url:
            return {}
        if action_step.url_matching == ActionStep.EXACT:
            return {'properties__$current_url': action_step.url}
        return {'properties__$current_url__icontains': action_step.url}

    def filter_by_event(self, action_step):
        if not action_step.event:
            return {}
        return {'event': action_step.event}

    def add_person_id(self, team_id: str):
        return self.annotate(person_id=Subquery(
            PersonDistinctId.objects.filter(team_id=team_id, distinct_id=OuterRef('distinct_id')).order_by().values('person_id')[:1]
        ))

    def query_db_by_action(self, action, order_by='-timestamp') -> models.QuerySet:
        events = self
        any_step = Q()
        steps = action.steps.all()
        if len(steps) == 0:
            return self.none()

        for step in steps:
            any_step |= Q(
                **self.filter_by_element(step),
                **self.filter_by_url(step),
                **self.filter_by_event(step)
            )
        events = self\
            .filter(team_id=action.team_id)\
            .filter(any_step)

        if order_by:
            events = events.order_by(order_by)

        return events

    def filter_by_action(self, action, order_by='-id') -> models.QuerySet:
        events = self.filter(action=action)\
            .add_person_id(team_id=action.team_id)
        if order_by:
            events = events.order_by(order_by)
        return events

    def filter_by_event_with_people(self, event, team_id, order_by='-id') -> models.QuerySet:
        events = self.filter(event=event)\
            .add_person_id(team_id=team_id)
        if order_by:
            events = events.order_by(order_by)
        return events

    def create(self, site_url: Optional[str] = None, *args: Any, **kwargs: Any):
        with transaction.atomic():
            if kwargs.get('elements'):
                if kwargs.get('team'):
                    kwargs['elements_hash'] = ElementGroup.objects.create(team=kwargs['team'], elements=kwargs.pop('elements')).hash
                else:
                    kwargs['elements_hash'] = ElementGroup.objects.create(team_id=kwargs['team_id'], elements=kwargs.pop('elements')).hash
            event = super().create(*args, **kwargs)
            should_post_to_slack = False
            relations = []
            for action in event.actions:
                relations.append(action.events.through(action_id=action.pk, event=event))
                if action.post_to_slack:
                    should_post_to_slack = True

            Action.events.through.objects.bulk_create(relations, ignore_conflicts=True)

            if should_post_to_slack and event.team and event.team.slack_incoming_webhook:
                post_event_to_slack.delay(event.id, site_url)

            return event

class Event(models.Model):
    class Meta:
        indexes = [
            models.Index(fields=['elements_hash']),
            models.Index(fields=['timestamp']),
        ]

    @property
    def person(self):
        return Person.objects.get(team_id=self.team_id, persondistinctid__distinct_id=self.distinct_id)

    # This (ab)uses query_db_by_action to find which actions match this event
    # We can't use filter_by_action here, as we use this function when we create an event so
    # the event won't be in the Action-Event relationship yet.
    @property
    def actions(self) -> List:
        actions = Action.objects.filter(team_id=self.team_id, steps__event=self.event).distinct('id')\
            .prefetch_related(Prefetch('steps', queryset=ActionStep.objects.order_by('id')))
        events: models.QuerySet[Any] = Event.objects.filter(pk=self.pk)
        for action in actions:
            events = events.annotate(**{'action_{}'.format(action.pk): Event.objects\
                .filter(pk=self.pk)\
                .query_db_by_action(action)\
                .values('id')[:1]
            })
        event = [event for event in events][0]

        return [action for action in actions if getattr(event, 'action_{}'.format(action.pk))]

    objects: EventManager = EventManager.as_manager() # type: ignore
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    event: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    distinct_id: models.CharField = models.CharField(max_length=200)
    properties: JSONField = JSONField(default=dict)
    elements: JSONField = JSONField(default=list, null=True, blank=True)
    timestamp: models.DateTimeField = models.DateTimeField(default=timezone.now, blank=True)
    elements_hash: models.CharField = models.CharField(max_length=200, null=True, blank=True)

class PersonManager(models.Manager):
    def create(self, *args: Any, **kwargs: Any):
        with transaction.atomic():
            if not kwargs.get('distinct_ids'):
                return super().create(*args, **kwargs)
            distinct_ids = kwargs.pop('distinct_ids')
            person = super().create(*args, **kwargs)
            person.add_distinct_ids(distinct_ids)
            return person

class Person(models.Model):
    @property
    def distinct_ids(self) -> List[str]:
        if hasattr(self, 'distinct_ids_cache'):
            return [id.distinct_id for id in self.distinct_ids_cache] # type: ignore
        return [id[0] for id in PersonDistinctId.objects.filter(person=self).order_by('id').values_list('distinct_id')]

    def add_distinct_id(self, distinct_id: str) -> None:
        PersonDistinctId.objects.create(person=self, distinct_id=distinct_id, team=self.team)

    def add_distinct_ids(self, distinct_ids: List[str]) -> None:
        for distinct_id in distinct_ids:
            self.add_distinct_id(distinct_id)

    objects = PersonManager()
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    properties: JSONField = JSONField(default=dict)
    is_user: models.ForeignKey = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)

class PersonDistinctId(models.Model):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['team', 'distinct_id'], name='unique distinct_id for team')
        ]
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    person: models.ForeignKey = models.ForeignKey(Person, on_delete=models.CASCADE)
    distinct_id: models.CharField = models.CharField(max_length=400)
    

class ElementGroupManager(models.Manager):
    def _hash_elements(self, elements: List) -> str:
        elements_list: List[Dict] = []
        for element in elements:
            el_dict = model_to_dict(element)
            [el_dict.pop(key) for key in ['event', 'id', 'group']]
            elements_list.append(el_dict)
        return hashlib.md5(json.dumps(elements_list, sort_keys=True, default=str).encode('utf-8')).hexdigest()

    def create(self, *args: Any, **kwargs: Any):
        elements = kwargs.pop('elements')
        with transaction.atomic():
            kwargs['hash'] = self._hash_elements(elements)
            try:
                with transaction.atomic():
                    group = super().create(*args, **kwargs)
            except:
                return ElementGroup.objects.get(
                    hash=kwargs['hash'],
                    team_id=kwargs['team'].pk if kwargs.get('team') else kwargs['team_id']
                )
            for element in elements:
                element.group = group
            for element in elements:
                setattr(element, 'pk', None)
            Element.objects.bulk_create(elements)
            return group

class ElementGroup(models.Model):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['team', 'hash'], name='unique hash for each team')
        ]
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    hash: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    objects = ElementGroupManager()

class Element(models.Model):
    USEFUL_ELEMENTS = ['a', 'button', 'input', 'select', 'textarea', 'label']
    text: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    tag_name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    href: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    attr_id: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    attr_class = ArrayField(models.CharField(max_length=200, blank=True), null=True, blank=True)
    nth_child: models.IntegerField = models.IntegerField(null=True, blank=True)
    nth_of_type: models.IntegerField = models.IntegerField(null=True, blank=True)
    attributes: JSONField = JSONField(default=dict)
    event: models.ForeignKey = models.ForeignKey(Event, on_delete=models.CASCADE, null=True, blank=True)
    order: models.IntegerField = models.IntegerField(null=True, blank=True)
    group: models.ForeignKey = models.ForeignKey(ElementGroup, on_delete=models.CASCADE, null=True, blank=True)


class Action(models.Model):
    def calculate_events(self):
        try:
            event_query, params = Event.objects.query_db_by_action(self).only('pk').query.sql_with_params()
        except: # make specific
            self.events.all().delete()
            return

        query = """
        DELETE FROM "posthog_action_events" WHERE "action_id" = {};
        INSERT INTO "posthog_action_events" ("action_id", "event_id")
        {}
        ON CONFLICT DO NOTHING
        """.format(
            self.pk,
            event_query.replace('SELECT ', 'SELECT {}, '.format(self.pk), 1)
        )

        cursor = connection.cursor()
        with transaction.atomic():
            cursor.execute(query, params)

    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)
    events: models.ManyToManyField = models.ManyToManyField(Event, blank=True)
    post_to_slack: models.BooleanField = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class ActionStep(models.Model):
    EXACT = 'exact'
    CONTAINS = 'contains'
    URL_MATCHING = [
        (EXACT, EXACT),
        (CONTAINS, CONTAINS),
    ]
    action: models.ForeignKey = models.ForeignKey(Action, related_name='steps', on_delete=models.CASCADE)
    tag_name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    text: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    href: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    selector: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    url: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    url_matching: models.CharField = models.CharField(max_length=400, choices=URL_MATCHING, default=CONTAINS, null=True, blank=True)
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    event: models.CharField = models.CharField(max_length=400, null=True, blank=True)


class Funnel(models.Model):
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    created_by: models.ForeignKey = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)
    filters: JSONField = JSONField(default=dict)

    def _order_people_in_step(self, steps: List[Dict[str, Any]], people: List[int]) -> List[int]:
        def order(person):
            score = 0
            for step in steps:
                if person in step['people']:
                    score += 1
            return (score, person)
        return sorted(people, key=order, reverse=True)

    def _annotate_steps(self, team_id: int, funnel_steps: QuerySet, date_query: Dict[str, datetime.date]) -> Dict[str, Subquery]:
        annotations = {}
        for index, step in enumerate(funnel_steps):
            filter_key = 'event' if step.get('type') == TREND_FILTER_TYPE_EVENTS else 'action__pk'
            annotations['step_{}'.format(index)] = Subquery(
                Event.objects.all()
                    .annotate(person_id=OuterRef('id'))
                    .filter(
                        **{filter_key: step['id']},
                        team_id=team_id,
                        distinct_id__in=Subquery(
                            PersonDistinctId.objects.filter(
                                team_id=team_id,
                                person_id=OuterRef('person_id')
                            ).values('distinct_id')
                        ),
                        **({'timestamp__gt': OuterRef('step_{}'.format(index-1))} if index > 0 else {}),
                        **date_query
                    )\
                    .order_by('timestamp')\
                    .values('timestamp')[:1])
        return annotations

    def _serialize_step(self, step: Dict[str, Any], people: Optional[List[int]] = None) -> Dict[str, Any]:
        if step.get('type') == TREND_FILTER_TYPE_ACTIONS:
            name = Action.objects.get(team=self.team_id, pk=step['id']).name
        else:
            name = step['id']
        return {
            'action_id': step['id'],
            'name': name,
            'order': step.get('order'),
            'people': people if people else [],
            'count': len(people) if people else 0
        }

    def get_steps(self) -> List[Dict[str, Any]]:
        funnel_steps = self.filters.get('actions', []) + self.filters.get('events', [])
        funnel_steps = sorted(funnel_steps, key=lambda step: step['order'])
        people = Person.objects.all()\
            .filter(
                team_id=self.team_id,
                persondistinctid__distinct_id__isnull=False
            )\
            .annotate(**self._annotate_steps(
                team_id=self.team_id,
                funnel_steps=funnel_steps,
                date_query=request_to_date_query(self.filters)
            ))\
            .filter(step_0__isnull=False)\
            .distinct('pk')

        steps = []
        for index, funnel_step in enumerate(funnel_steps):
            relevant_people = [person.id for person in people if getattr(person, 'step_{}'.format(index))]
            steps.append(self._serialize_step(funnel_step, relevant_people))

        if len(steps) > 0:
            for index, _ in enumerate(steps):
                steps[index]['people'] = self._order_people_in_step(steps, steps[index]['people'])[0:100]
        return steps

class FunnelStep(models.Model):
    funnel: models.ForeignKey = models.ForeignKey(Funnel, related_name='steps', on_delete=models.CASCADE)
    action: models.ForeignKey = models.ForeignKey(Action, on_delete=models.CASCADE)
    order: models.IntegerField = models.IntegerField()

class DashboardItem(models.Model):
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    filters: JSONField = JSONField(default=dict)
    order: models.IntegerField = models.IntegerField(null=True, blank=True)
    type: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)

class Cohort(models.Model):
    @property
    def people(self):
        return Person.objects.filter(self.people_filter, team=self.team_id)

    @property
    def people_filter(self):
        filters = Q()
        for group in self.groups:
            if group.get('action_id'):
                action = Action.objects.get(pk=group['action_id'], team_id=self.team_id)
                events = Event.objects.filter_by_action(action).filter(
                    team_id=self.team_id,
                    **({'timestamp__gt' : timezone.now() - relativedelta(days=group['days'])} if group.get('days') else {})
                ).order_by('distinct_id').distinct('distinct_id').values('distinct_id')

                filters |= Q(
                    persondistinctid__distinct_id__in=events
                )
            elif group.get('properties'):
                properties = properties_to_Q(group['properties'])
                filters |= Q(
                    properties
                )
        return filters 

    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    deleted: models.BooleanField = models.BooleanField(default=False)
    groups: JSONField = JSONField(default=list)
