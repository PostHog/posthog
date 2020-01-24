from django.db import models
from django.contrib.postgres.fields import JSONField
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
    elements: JSONField = JSONField(default=list)
    timestamp: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    ip: models.GenericIPAddressField = models.GenericIPAddressField()

class Person(models.Model):
    distinct_ids: JSONField = JSONField(default=list)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    properties: JSONField = JSONField(default=dict)
    is_user: models.ForeignKey = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)