from django.db import models

from posthog.models.utils import CreatedMetaFields, RootTeamMixin, UpdatedMetaFields, UUIDTModel, sane_repr


class InsightVariable(UUIDTModel, RootTeamMixin, CreatedMetaFields, UpdatedMetaFields):
    class Type(models.TextChoices):
        STRING = "String", "String"
        NUMBER = "Number", "Number"
        BOOLEAN = "Boolean", "Boolean"
        LIST = "List", "List"
        DATE = "Date", "Date"

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=400)
    code_name = models.CharField(max_length=400, null=True, blank=True)
    type = models.CharField(max_length=128, choices=Type.choices)
    default_value = models.JSONField(null=True, blank=True)
    values = models.JSONField(null=True, blank=True)

    __repr__ = sane_repr("id")
