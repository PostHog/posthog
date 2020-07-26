from django.db import models
from .user import User
from datetime import datetime
from .utils import generate_random_token


class PersonalAPIKey(models.Model):
    id: models.CharField = models.CharField(primary_key=True, max_length=40, default=generate_random_token)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="personal_api_keys")
    label: models.CharField = models.CharField(max_length=40)
    value: models.CharField = models.CharField(
        unique=True, max_length=40, default=generate_random_token, editable=False
    )
    created_at: models.DateTimeField = models.DateTimeField(default=datetime.now)
    last_used_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
