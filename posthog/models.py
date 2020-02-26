from django.db import models
from django.contrib.postgres.fields import JSONField, ArrayField
from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils.translation import ugettext_lazy as _
from django.dispatch import receiver
from django.forms.models import model_to_dict
from django.utils import timezone
from typing import List, Tuple, Optional, Any, Union, Dict
from django.db import transaction
from sentry_sdk import capture_exception
from dateutil.relativedelta import relativedelta

import secrets
import re

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
            tag = result[1]
        if '[' in tag:
            result = re.search(attribute_regex, tag)
            data['attributes__{}'.format(result[2])] = result[3] # type: ignore
            tag = result[1]
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

class UserManager(BaseUserManager):
    """Define a model manager for User model with no username field."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        """Create and save a User with the given email and password."""
        if not email:
            raise ValueError('The given email must be set')
        email = self.normalize_email(email)
        if hasattr(settings, 'RESTRICT_SIGNUPS') and settings.RESTRICT_SIGNUPS and email.rsplit('@', 1)[1] not in settings.RESTRICT_SIGNUPS.split(','):
            raise ValueError("Can't sign up with this email")
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
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

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS: List[str] = []

    objects = UserManager() # type: ignore


class TeamManager(models.Manager):
    def create_with_data(self, users: List[User]=None, **kwargs):
        team = Team.objects.create(**kwargs)
        if users:
            team.users.set(users)

        action = Action.objects.create(team=team, name='Pageviews')
        ActionStep.objects.create(action=action, event='$pageview')

        DashboardItem.objects.create(team=team, name='Pageviews this week', type='ActionsLineGraph', filters={'actions': [action.pk]})
        DashboardItem.objects.create(
            team=team,
            name='Most popular browsers this week',
            type='ActionsTable',
            filters={'actions': [action.pk], 'display': 'ActionsTable', 'breakdown': '$browser'}
        )
        DashboardItem.objects.create(
            team=team,
            name='All actions',
            type='ActionsLineGraph',
            filters={}
        )
        return team


class Team(models.Model):
    users: models.ManyToManyField = models.ManyToManyField(User, blank=True)
    api_token: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    app_url: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    name: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    opt_out_capture: models.BooleanField = models.BooleanField(default=False)

    objects = TeamManager()

    def __str__(self):
        if self.name:
            return self.name
        if self.app_url:
            return self.app_url
        return str(self.pk)

@receiver(models.signals.post_save, sender=Team)
def create_team_signup_token(sender, instance, created, **kwargs):
    # Don't do this when running tests to speed up
    if created and not settings.TEST:
        if not instance.api_token:
            instance.api_token = secrets.token_urlsafe(32)
            instance.save()

class EventManager(models.Manager):
    def _handle_class(self, index, item, where, params):
        where.append("AND E{}.attr_class @> %s::varchar(200)[]".format(index))
        params.append(item)

    def _handle_attributes(self, index: int, key: str, value: str, where: List[str], params: List[str]):
        where.append("AND E{}.attributes ->> %s = %s".format(index))
        params.extend([key.replace('attributes__', ''), value])

    def _filter_selector(self, filters, joins, where, params):
        selector = filters.pop('selector')
        parts = split_selector_into_parts(selector)
        for index, tag in enumerate(parts):
            for key, value in tag.items():
                if key == 'attr_class':
                    self._handle_class(index, value, where=where, params=params)
                elif 'attributes__' in key:
                    self._handle_attributes(index, key, value, where=where, params=params)
                else:
                    where.append("AND E{}.{} = %s".format(index, key))
                    params.append(value)
            if index > 0:
                joins.append('INNER JOIN posthog_element E{0} ON (posthog_event.id = E{0}.event_id)'.format(index))
                where.append('AND E{0}.order = (( E{1}.order + 1))'.format(index, index-1))

    def _filters(self, filters, where: List, params: List):
        for key, value in filters.items():
            if key == 'url' and value:
                where.append('AND posthog_event.properties ->> \'$current_url\' LIKE %s')
                params.append('%{}%'.format(value))
            elif key == 'event' and value:
                where.append('AND posthog_event.event = %s')
                params.append(value)
            elif key not in ['action', 'id', 'selector'] and value:
                where.append('AND E0.{} = %s'.format(key))
                params.append(value)

    def _step(self, step, joins: List, where: List, params: List):
        filters = model_to_dict(step)
        where.append(' OR (1=1 ')
        if filters['selector']:
            filter_selector = self._filter_selector(filters, joins=joins, where=where, params=params)
        self._filters(filters, where=where, params=params)
        where.append(')')

    def _select(self, count=None, group_by=None, group_by_table=None, count_by=None):
        if count_by:
            return "SELECT date_trunc('{0}', posthog_event.timestamp) as {0}, COUNT(1) as id FROM posthog_event ".format(count_by)
        if group_by:
            return "SELECT DISTINCT ON (posthog_persondistinctid.person_id) {}.{} as id, posthog_event.id as event_id FROM posthog_event ".format(group_by_table, group_by)
        if count:
            return "SELECT COUNT(posthog_event.id) as id FROM posthog_event "
        return """
        SELECT "posthog_event"."id",
            "posthog_event"."team_id",
            "posthog_event"."event",
            "posthog_event"."distinct_id",
            "posthog_event"."properties",
            "posthog_event"."elements",
            "posthog_event"."timestamp",
            "posthog_event"."ip",
            "posthog_persondistinctid"."person_id" as person_id
        FROM   "posthog_event" """

    def filter_by_action(self, action, count: Optional[bool]=None, group_by: Optional[str]=None, count_by: Optional[str]=None, group_by_table: Optional[str]=None, limit: Optional[int]=None, where: Optional[Union[str, List[Any]]]=None) -> models.query.RawQuerySet:
        query = self._select(count=count, group_by=group_by, group_by_table=group_by_table, count_by=count_by)

        joins: List[str] = [
            'INNER JOIN posthog_persondistinctid ON (posthog_event.distinct_id = posthog_persondistinctid.distinct_id AND posthog_persondistinctid.team_id = {}) '.format(action.team_id),
            'LEFT OUTER JOIN posthog_element E0 ON (posthog_event.id = E0.event_id)'
        ]
        where_list: List[str] = []
        params: List[str] = []

        for step in action.steps.all():
            self._step(step, joins=joins, where=where_list, params=params)

        query += ' '.join(joins)
        query += ' WHERE '
        query += ' posthog_event.team_id = {}'.format(action.team_id)
        query += ' AND (1=2 '
        query += ' '.join(where_list)
        query += ') '
        if where:
            if isinstance(where, list):
                for w in where:
                    query += ' AND {}'.format(w[0])
                    params.extend(w[1])
            elif where != '':
                query += ' AND ({})'.format(where)

        if group_by:
            query += ' GROUP BY {}.{}, posthog_event.id'.format(group_by_table, group_by)
        if count_by:
            query += ' GROUP BY day'
        if not count and not group_by and not count_by:
            query += ' ORDER BY posthog_event.timestamp DESC'
        if limit:
            query += ' LIMIT %s' % limit
        events = Event.objects.raw(query, params)
        if count:
            return events[0].id # bit of a hack to get the total count here
        return events


class Event(models.Model):
    @property
    def person(self):
        return Person.objects.get(team_id=self.team_id, persondistinctid__distinct_id=self.distinct_id)

    def _element_matches_selector(self, elements, selector: Dict, order=None):
        for element in elements:
            if order not in (None, element.order):
                continue
            if selector.get('tag_name') and selector['tag_name'] != element.tag_name:
                continue
            if selector.get('attr_class') and (not element.attr_class or not all(name in element.attr_class for name in selector['attr_class'])):
                continue
            if selector.get('nth_child') and selector['nth_child'] != element.nth_child:
                continue
            if selector.get('attr_id') and selector['attr_id'] != element.attr_id:
                continue
            attribute_key = [(key.replace('attributes__', ''), selector[key]) for key in selector.keys() if 'attributes__' in key]
            if len(attribute_key) > 0 and element.attributes.get(attribute_key[0][0]) != attribute_key[0][1]:
                continue
            return element
        return False

    def _event_matches_selector(self, event, selector: str) -> bool:
        elements = event.element_set.all()
        prev = None
        parts = split_selector_into_parts(selector)
        for tag in parts:
            prev = self._element_matches_selector(
                elements=elements,
                order=prev.order + 1 if prev else None, # type: ignore
                selector=tag)
            if not prev:
                return False
        return True

    def _element_matches_step(self, filters: Dict, element) -> bool:
        match = True
        for key, value in filters.items():
            if getattr(element, key) != value:
                match = False
        return match

    def _event_matches_step(self, event, step) -> bool:
        filters = model_to_dict(step)
        filters.pop('action')
        filters.pop('id')
        filters = {key: value for key, value in filters.items() if value}

        if filters.get('url'):
            if event.properties.get('$current_url') != filters['url']:
                return False
            filters.pop('url')
        if filters.get('event'):
            if event.event != filters['event']:
                return False
            filters.pop('event')
        if len(filters.keys()) == 0 and event.element_set.count() == 0:
            # if no more filters to apply, and no elements, means it was a pageview/event filter so can return
            return True
        if filters.get('selector'):
            if not self._event_matches_selector(event, filters['selector']):
                return False
            filters.pop('selector')
        for element in event.element_set.all():
            if self._element_matches_step(filters, element):
                return True
        return False

    @property
    def actions(self) -> List:
        action_steps = ActionStep.objects.filter(action__team_id=self.team_id).select_related('action')
        actions: List[Dict] = []
        for step in action_steps:
            if step.action not in actions:
                if self._event_matches_step(self, step):
                    actions.append(step.action)
        return actions

    objects = EventManager()
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    event: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    distinct_id: models.CharField = models.CharField(max_length=200)
    properties: JSONField = JSONField(default=dict)
    elements: JSONField = JSONField(default=list, null=True, blank=True)
    timestamp: models.DateTimeField = models.DateTimeField(default=timezone.now, blank=True)
    ip: models.GenericIPAddressField = models.GenericIPAddressField(null=True, blank=True)

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
    event: models.ForeignKey = models.ForeignKey(Event, on_delete=models.CASCADE)
    order: models.IntegerField = models.IntegerField(null=True, blank=True)

class Action(models.Model):
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)

    def __str__(self):
        return self.name

class ActionStep(models.Model):
    action: models.ForeignKey = models.ForeignKey(Action, related_name='steps', on_delete=models.CASCADE)
    tag_name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    text: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    href: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    selector: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    url: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    event: models.CharField = models.CharField(max_length=400, null=True, blank=True)

class Funnel(models.Model):
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    created_by: models.ForeignKey = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)

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
    def distinct_ids(self) -> List[str]:
        return [d for d in PersonDistinctId.objects.filter(team_id=self.team_id, person_id__in=self.person_ids).values_list('distinct_id', flat=True)]

    @property
    def person_ids(self):
        person_ids = []
        for group in self.groups:
            if group.get('action_id'):
                date_from = timezone.now() - relativedelta(days=group['days']) if group.get('days') else None
                person_ids.extend([person.id for person in Event.objects.filter_by_action(
                    Action.objects.get(pk=group['action_id'], team_id=self.team_id),
                    where=[['posthog_event.timestamp > %s', [date_from]]] if date_from else None,
                    group_by='person_id',
                    group_by_table='posthog_persondistinctid')])
            elif group.get('properties'):
                person_ids.extend(
                    [person_id for person_id in Person.objects.filter(team_id=self.team_id, properties__contains=group['properties']).order_by('-id').values_list('pk', flat=True)]
                )
        return person_ids

    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    deleted: models.BooleanField = models.BooleanField(default=False)
    groups: JSONField = JSONField(default=list)