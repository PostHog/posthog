from django.db import models

from posthog.models.utils import CreatedMetaFields, UUIDModel, UpdatedMetaFields, sane_repr


class InsightVariable(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    class Type(models.TextChoices):
        STRING = "String", "String"
        NUMBER = "Number", "Number"
        BOOLEAN = "Boolean", "Boolean"
        LIST = "List", "List"

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=400)
    code_name = models.CharField(max_length=400, null=True, blank=True)
    type = models.CharField(max_length=128, choices=Type.choices)
    default_value = models.JSONField(null=True, blank=True)

    __repr__ = sane_repr("id")
