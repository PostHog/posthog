from django.db import models


class GroupTypeMapping(models.Model):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "type_key"], name="unique_group types for team"),
            models.UniqueConstraint(fields=["team", "type_id"], name="unique group type ids for team"),
            models.CheckConstraint(check=models.Q(type_id__lte=5), name="type_id is less than or equal 5"),
        ]

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    type_key: models.CharField = models.CharField(max_length=400, null=False, blank=False)  # TODO? Rename to type_name
    type_id: models.IntegerField = models.IntegerField(null=False, blank=False)  # TODO? Rename to type_index
