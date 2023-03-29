from django.db import models


class DataBeachFieldType(models.TextChoices):
    Datetime = "DateTime", "DateTime"
    String = "String", "String"
    Boolean = "Boolean", "Boolean"
    Integer = "Integer", "Integer"
    Float = "Float", "Float"


class DataBeachField(models.Model):
    team: models.ForeignKey = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    table: models.ForeignKey = models.ForeignKey(
        "posthog.DataBeachTable", related_name="fields", on_delete=models.CASCADE
    )
    name: models.CharField = models.CharField(max_length=255, null=False, blank=False)
    type: models.CharField = models.CharField(
        max_length=100, null=False, blank=False, choices=DataBeachFieldType.choices, default=None
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "table", "name"], name="unique_name_per_team_per_table"),
        ]
