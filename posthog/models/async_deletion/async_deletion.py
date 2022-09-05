from django.db import models


class DeletionType(models.IntegerChoices):
    Team = 0
    Person = 1
    Group = 2


# This model represents deletions that should delete (other, unrelated) data async
class AsyncDeletion(models.Model):
    class Meta:
        constraints = [
            # :TRICKY: Postgres does not handle UNIQUE and NULL together well, so create 2 indexes.
            # See https://dba.stackexchange.com/questions/9759/postgresql-multi-column-unique-constraint-and-null-values for more details
            models.UniqueConstraint(
                name="unique deletion",
                fields=["deletion_type", "key"],
                condition=models.Q(group_type_index__isnull=True),
            ),
            models.UniqueConstraint(
                name="unique deletion for groups", fields=["deletion_type", "key", "group_type_index"]
            ),
        ]
        indexes = [models.Index(name="delete_verified_at index", fields=["delete_verified_at"])]

    id: models.BigAutoField = models.BigAutoField(primary_key=True)
    # Should be one of the DeletionType enum
    deletion_type: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(null=False, blank=False)

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)

    # id for team (same as team_id column), uuid for person, key for group
    key: models.CharField = models.CharField(max_length=400, null=False, blank=False)
    # Only populated for group deletions
    group_type_index: models.IntegerField = models.IntegerField(null=True, blank=False)

    created_by: models.ForeignKey = models.ForeignKey("User", null=True, on_delete=models.SET_NULL)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    # When was the data verified to be deleted - we can skip it in the next round
    delete_verified_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
