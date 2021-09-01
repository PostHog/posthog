from django.db import models


class GroupTypeMapping(models.Model):
    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "type_key"], name="unique group types for team")]
        constraints = [models.UniqueConstraint(fields=["team", "type_id"], name="unique group type ids for team")]

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    type_key: models.CharField = models.CharField(max_length=400, null=False, blank=False)
    type_id: models.IntegerField = models.IntegerField(null=False, blank=False)
