from django.db import models
from django.db.models import Exists, OuterRef, Q, Subquery, F
from django.contrib.postgres.fields import JSONField, ArrayField
from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils.translation import ugettext_lazy as _
from django.dispatch import receiver
from django.forms.models import model_to_dict
from django.utils import timezone
from posthog.utils import properties_to_Q
from typing import List, Tuple, Optional, Any, Union, Dict
from django.db import transaction
from sentry_sdk import capture_exception
from dateutil.relativedelta import relativedelta

import secrets
import re
import json
import hashlib

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

    objects: UserManager = UserManager() # type: ignore


class TeamManager(models.Manager):
    def create_with_data(self, users: List[User]=None, **kwargs):
        kwargs['api_token'] = kwargs.get('api_token', secrets.token_urlsafe(32))
        kwargs['signup_token'] = kwargs.get('signup_token', secrets.token_urlsafe(22))
        team = Team.objects.create(**kwargs)
        if users:
            team.users.set(users)

        action = Action.objects.create(team=team, name='Pageviews')
        ActionStep.objects.create(action=action, event='$pageview')

        DashboardItem.objects.create(team=team, name='Pageviews this week', type='ActionsLineGraph', filters={'actions': [{'id': action.pk}]})
        DashboardItem.objects.create(
            team=team,
            name='Most popular browsers this week',
            type='ActionsTable',
            filters={'actions': [{'id': action.pk}], 'display': 'ActionsTable', 'breakdown': '$browser'}
        )
        return team


class Team(models.Model):
    users: models.ManyToManyField = models.ManyToManyField(User, blank=True)
    api_token: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    signup_token: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    app_urls: ArrayField = ArrayField(models.CharField(max_length=200, null=True, blank=True), default=list)
    name: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    opt_out_capture: models.BooleanField = models.BooleanField(default=False)

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
        for key in ['tag_name', 'text', 'href', 'name']:
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
            groups = groups.annotate(**subqueries)
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

    def add_person_id(self, action):
        return self.annotate(person_id=Subquery(
            PersonDistinctId.objects.filter(team_id=action.team_id, distinct_id=OuterRef('distinct_id')).order_by().values('person_id')[:1]
        ))

    def filter_by_action(self, action) -> models.QuerySet:
        events = self
        any_step = Q()
        for step in action.steps.all():
            any_step |= Q(
                **self.filter_by_element(step),
                **self.filter_by_url(step),
                **self.filter_by_event(step)
            )
        events = self\
            .filter(team_id=action.team_id)\
            .add_person_id(action)\
            .filter(any_step)\
            .order_by('-id')
        return events

    def create(self, *args: Any, **kwargs: Any):
        with transaction.atomic():
            if kwargs.get('elements'):
                kwargs['elements_hash'] = ElementGroup.objects.create(team=kwargs['team'], elements=kwargs.pop('elements')).hash
            return super().create(*args, **kwargs)


class Event(models.Model):
    class Meta:
        indexes = [models.Index(fields=['elements_hash']),]

    @property
    def person(self):
        return Person.objects.get(team_id=self.team_id, persondistinctid__distinct_id=self.distinct_id)

    objects: EventManager = EventManager.as_manager()
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    event: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    distinct_id: models.CharField = models.CharField(max_length=200)
    properties: JSONField = JSONField(default=dict)
    elements: JSONField = JSONField(default=list, null=True, blank=True)
    timestamp: models.DateTimeField = models.DateTimeField(default=timezone.now, blank=True)
    ip: models.GenericIPAddressField = models.GenericIPAddressField(null=True, blank=True)
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
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)

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
    url_matching: models.CharField = models.CharField(max_length=400, choices=URL_MATCHING, default=CONTAINS)
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
                action = Action.objects.get(pk=group['action_id'], team_id=self.team_id)
                people = Person.objects.filter(
                    team_id=self.team_id,
                ).annotate(
                    has_action=Subquery(
                        Event.objects.filter_by_action(
                            action
                        ).filter(
                            person_id=OuterRef('id'),
                            **({'timestamp__gt' : timezone.now() - relativedelta(days=group['days'])} if group.get('days') else {})
                        ).values('id')[:1]
                    )
                ).filter(
                    has_action__isnull=False
                )
                person_ids.extend([person.id for person in people])
            elif group.get('properties'):
                properties = properties_to_Q(group['properties'])
                person_ids.extend(
                    [person_id for person_id in Person.objects.filter(properties, team_id=self.team_id).order_by('-id').values_list('pk', flat=True)]
                )
        return person_ids

    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    deleted: models.BooleanField = models.BooleanField(default=False)
    groups: JSONField = JSONField(default=list)
