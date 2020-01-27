from django.db import models
from django.contrib.postgres.fields import JSONField, ArrayField
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.dispatch import receiver
from django.forms.models import model_to_dict

import secrets
import re


class User(AbstractUser):
    pass


class Team(models.Model):
    users: models.ManyToManyField = models.ManyToManyField(User, blank=True)    
    api_token: models.CharField = models.CharField(max_length=200, null=True, blank=True)

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
            if key != 'action' and key != 'id' and key != 'selector' and value:
                self.where.append('AND E0.{} = %s'.format(key))
                self.params.append(value)

    def _step(self, step):
        filters = model_to_dict(step)
        self.where.append(' OR (1=1 ')
        if filters['selector']:
            self._filter_selector(filters)
        self._filters(filters)
        self.where.append(')')

    def _select(self, count):
        if count:
            return "SELECT COUNT(posthog_event.id) as id FROM posthog_event "
        else:
            return """
            SELECT "posthog_event"."id", 
                "posthog_event"."team_id", 
                "posthog_event"."event", 
                "posthog_event"."properties", 
                "posthog_event"."elements", 
                "posthog_event"."timestamp", 
                "posthog_event"."ip" 
            FROM   "posthog_event" """

    def filter_by_action(self, action, count=False):
        query = self._select(count=count)
        
        self.joins = ['INNER JOIN posthog_element E0 ON (posthog_event.id = E0.event_id)']
        self.where = []
        self.params = []

        for step in action.steps.all():
            self._step(step)

        query += ' '.join(self.joins)
        query += ' WHERE 1=2 '
        query += ' '.join(self.where)
        events = Event.objects.raw(query, self.params)
        if count:
            return events[0].id # bit of a hack to get the total count here
        return events



class Event(models.Model):
    objects = EventManager()
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    event: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    properties: JSONField = JSONField(default=dict)
    elements: JSONField = JSONField(default=list, null=True, blank=True)
    timestamp: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    ip: models.GenericIPAddressField = models.GenericIPAddressField()

class Person(models.Model):
    distinct_ids: ArrayField = ArrayField(models.CharField(max_length=400, blank=True), null=True, blank=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    properties: JSONField = JSONField(default=dict)
    is_user: models.ForeignKey = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)


class Element(models.Model):
    USEFUL_ELEMENTS = ['a', 'button', 'input', 'select', 'textarea', 'label']
    text: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    tag_name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    href: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    attr_id: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    nth_child: models.IntegerField = models.IntegerField()
    nth_of_type: models.IntegerField = models.IntegerField()
    attributes: JSONField = JSONField(default=dict)
    event: models.ForeignKey = models.ForeignKey(Event, on_delete=models.CASCADE)
    order: models.IntegerField = models.IntegerField()

class Action(models.Model):
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)

class ActionStep(models.Model):
    action: models.ForeignKey = models.ForeignKey(Action, related_name='steps', on_delete=models.CASCADE)
    tag_name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    text: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    href: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    selector: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    url: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)