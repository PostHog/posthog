from django.db import models


class Group(models.Model):
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team_id", "group_key", "group_type_index"],
                name="unique team_id/group_key/group_type_index combo",
            )
        ]

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    group_key: models.CharField = models.CharField(max_length=400, null=False, blank=False)
    group_type_index: models.IntegerField = models.IntegerField(null=False, blank=False)

    group_properties: models.JSONField = models.JSONField(default=dict)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    # used to prevent race conditions with set and set_once
    properties_last_updated_at: models.JSONField = models.JSONField(default=dict)

    # used for evaluating if we need to override the value or not (value: set or set_once)
    properties_last_operation: models.JSONField = models.JSONField(default=dict)

    # current version of the group, used to sync with ClickHouse and collapse rows correctly
    version: models.BigIntegerField = models.BigIntegerField(null=False)
