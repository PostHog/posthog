from django.db import models


# This table is responsible for mapping between group types for a Team/Project and event columns
# to add group keys
class GroupTypeMapping(models.Model):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "group_type"], name="unique group types for team"),
            models.UniqueConstraint(fields=["team", "group_type_index"], name="unique event column indexes for team"),
            models.CheckConstraint(
                check=models.Q(group_type_index__lte=5), name="group_type_index is less than or equal 5"
            ),
        ]

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    group_type: models.CharField = models.CharField(max_length=400, null=False, blank=False)
    group_type_index: models.IntegerField = models.IntegerField(null=False, blank=False)
