from typing import Any, Dict, List

from django.db import models


class Settings(models.Model):
    """
    This table represents a one row table that has dynamic settings that could be environmental variables
    But for whatever reason need to by synchronized between containers (example: migrations)
    Another potential reason is for settings that could be set from a dashboard within the app (SMTP mail settings)
    Note: This is a table that will always have one row. Think of it as a singleton model
    """

    lock: models.CharField = models.CharField(max_length=1, null=False, primary_key=True, default="X")
    materialized_columns_enabled: models.BooleanField = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        self.pk = "X"
        super().save(*args, **kwargs)


def get_from_db(key: str, default: Any = None) -> Any:
    try:
        value = Settings.objects.values(key.lower()).first()
    except Exception as e:
        print(e)
        value = default
    return value


def materialized_columns_enabled():
    return get_from_db("materialized_columns_enabled", True)
