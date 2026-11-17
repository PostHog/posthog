from django.db import models
from django.utils import timezone


class UserAnalyticsDeletion(models.Model):
    # No user FK: the request must survive the account's deletion.
    distinct_id = models.CharField(max_length=200, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    next_attempt_at = models.DateTimeField(db_index=True)
