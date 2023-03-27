from django.db import models


class DataFieldType(models.TextChoices):
    Datetime = "DateTime", "DateTime"
    String = "String", "String"
    Boolean = "Boolean", "Boolean"
    Integer = "Integer", "Integer"
    Float = "Float", "Float"


class DataField(models.Model):
    team: models.ForeignKey = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    table: models.ForeignKey = models.ForeignKey("posthog.DataTable", on_delete=models.CASCADE)
    name: models.CharField = models.CharField(max_length=255, null=False, blank=False)
    type: models.CharField = models.CharField(
        max_length=100, null=False, blank=False, choices=DataFieldType.choices, default=None
    )
