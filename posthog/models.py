from django.db import models
from django.contrib.postgres.fields import JSONField, ArrayField
from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils.translation import ugettext_lazy as _
from django.dispatch import receiver
from django.forms.models import model_to_dict
from typing import List, Tuple, Optional, Any, Union
from django.db import transaction

import secrets
import re



class UserManager(BaseUserManager):
    """Define a model manager for User model with no username field."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        """Create and save a User with the given email and password."""
        if not email:
            raise ValueError('The given email must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a regular User with the given email and password."""
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
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

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS: List[str] = []

    objects = UserManager() # type: ignore


class Team(models.Model):
    users: models.ManyToManyField = models.ManyToManyField(User, blank=True)    
    api_token: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    app_url: models.CharField = models.CharField(max_length=200, null=True, blank=True)

    def __str__(self):
        return self.app_url if self.app_url else str(self.pk)

@receiver(models.signals.post_save, sender=Team)
def create_team_signup_token(sender, instance, created, **kwargs):
    # Don't do this when running tests to speed up
    if created and not settings.TEST:
        if not instance.api_token:
            instance.api_token = secrets.token_urlsafe(10)
            instance.save()

class EventManager(models.Manager):
    def _handle_nth_child(self, index, tag):
        nth_child_regex =  r"([a-z]+):nth-child\(([0-9]+)\)"
        nth_child = re.match(nth_child_regex, tag)
        self.where.append("AND E{}.tag_name = %s".format(index))
        self.params.append(nth_child[1])
        self.where.append("AND E{}.nth_child = {}".format(index, nth_child[2]))

    def _handle_id(self, index, tag):
        id_regex =  r"\[id=\'(.*)']"
        result = re.match(id_regex, tag)
        self.where.append("AND E{}.attr_id = %s".format(index))
        self.params.append(result[1])

    def _filter_selector(self, filters):
        selector = filters.pop('selector')
        tags = selector.split(' > ')
        tags.reverse()
        for index, tag in enumerate(tags):
            if 'nth-child' in tag:
                self._handle_nth_child(index, tag)
            elif 'id=' in tag:
                self._handle_id(index, tag)
            else:
                self.where.append("AND E{}.tag_name = %s".format(index))
                self.params.append(tag)
            if index > 0:
                self.joins.append('INNER JOIN posthog_element E{0} ON (posthog_event.id = E{0}.event_id)'.format(index))
                self.where.append('AND E{0}.order = (( E{1}.order + 1))'.format(index, index-1))

    def _filters(self, filters):
        for key, value in filters.items():
            if key == 'url' and value:
                self.where.append('AND posthog_event.properties ->> \'$current_url\' LIKE %s')
                self.params.append('%{}%'.format(value))
            elif key not in ['action', 'id', 'selector'] and value:
                self.where.append('AND E0.{} = %s'.format(key))
                self.params.append(value)

    def _step(self, step):
        filters = model_to_dict(step)
        self.where.append(' OR (1=1 ')
        if filters['selector']:
            self._filter_selector(filters)
        self._filters(filters)
        self.where.append(')')

    def _select(self, count=None, group_by=None, group_by_table=None):
        if group_by:
            return "SELECT DISTINCT ON (posthog_persondistinctid.person_id) {}.{} as id, posthog_event.id as event_id FROM posthog_event ".format(group_by_table, group_by)
        if count:
            return "SELECT COUNT(posthog_event.id) as id FROM posthog_event "
        return """
        SELECT "posthog_event"."id", 
            "posthog_event"."team_id", 
            "posthog_event"."event", 
            "posthog_event"."properties",
            "posthog_event"."elements", 
            "posthog_event"."timestamp", 
            "posthog_event"."ip",
            "posthog_persondistinctid"."person_id" as person_id
        FROM   "posthog_event" """

    def filter_by_action(self, action, count: Optional[bool]=None, group_by: Optional[str]=None, group_by_table: Optional[str]=None, limit: Optional[int]=None, where: Optional[Union[str, List[Any]]]=None) -> models.query.RawQuerySet:
        query = self._select(count=count, group_by=group_by, group_by_table=group_by_table)
        
        self.joins: List[str] = [
            'RIGHT OUTER JOIN posthog_persondistinctid ON (posthog_event.distinct_id = posthog_persondistinctid.distinct_id) ',
            'INNER JOIN posthog_element E0 ON (posthog_event.id = E0.event_id)'
         ]
        self.where: List[str] = []
        self.params: List[str] = []

        for step in action.steps.all():
            self._step(step)

        query += ' '.join(self.joins)
        query += ' WHERE (1=2 '
        query += ' '.join(self.where)
        query += ') '
        if where:
            if isinstance(where, list):
                query += ' AND {} %s'.format(where[0])
                self.params.append(where[1])
            elif where != '':
                query += ' AND ({})'.format(where)
        if group_by:
            query += ' GROUP BY {}.{}, posthog_event.id'.format(group_by_table, group_by)
        if not count and not group_by:
            query += ' ORDER BY posthog_event.timestamp DESC'
        if limit:
            query += ' LIMIT %s' % limit
        events = Event.objects.raw(query, self.params)
        if count:
            return events[0].id # bit of a hack to get the total count here
        return events


class Event(models.Model):
    @property
    def person(self):
        return Person.objects.get(team=self.team, persondistinctid__distinct_id=self.distinct_id)

    objects = EventManager()
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    event: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    distinct_id: models.CharField = models.CharField(max_length=200)
    properties: JSONField = JSONField(default=dict)
    elements: JSONField = JSONField(default=list, null=True, blank=True)
    timestamp: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    ip: models.GenericIPAddressField = models.GenericIPAddressField(null=True, blank=True)

    def __str__(self):
        return self.event

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
        return [id[0] for id in PersonDistinctId.objects.filter(person=self).values_list('distinct_id')]

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

class Funnel(models.Model):
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    created_by: models.ForeignKey = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)

class FunnelStep(models.Model):
    funnel: models.ForeignKey = models.ForeignKey(Funnel, related_name='steps', on_delete=models.CASCADE)
    action: models.ForeignKey = models.ForeignKey(Action, on_delete=models.CASCADE)
    order: models.IntegerField = models.IntegerField()