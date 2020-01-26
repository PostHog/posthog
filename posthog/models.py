from django.db import models
from django.contrib.postgres.fields import JSONField, ArrayField
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.dispatch import receiver

import secrets


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


class Event(models.Model):
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
    el_text: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    tag_name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    href: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    attr_id: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    nth_child: models.IntegerField = models.IntegerField()
    nth_of_type: models.IntegerField = models.IntegerField()
    attributes: JSONField = JSONField(default=dict)
    event: models.ForeignKey = models.ForeignKey(Event, on_delete=models.CASCADE)
    order: models.IntegerField = models.IntegerField()
