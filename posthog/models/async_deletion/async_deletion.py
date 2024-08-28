from django.db import models


class DeletionType(models.IntegerChoices):
    Team = 0
    Person = 1
    Group = 2
    Cohort_stale = 3
    Cohort_full = 4


# This model represents deletions that should delete (other, unrelated) data async
class AsyncDeletion(models.Model):
    id = models.BigAutoField(primary_key=True)
    # Should be one of the DeletionType enum
    deletion_type = models.PositiveSmallIntegerField(null=False, blank=False, choices=DeletionType.choices)

    # Team whose data shall be deleted. This is not a foreign key, because we still need this value
    # when the team is gone (we are talking about _async_ deletions after all)
    team_id = models.IntegerField()

    # id for team (same as team_id column), uuid for person, key for group
    key = models.CharField(max_length=400, null=False, blank=False)
    # Only populated for group deletions
    group_type_index = models.IntegerField(null=True, blank=False)

    created_by = models.ForeignKey("User", null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    # When was the data verified to be deleted - we can skip it in the next round
    delete_verified_at = models.DateTimeField(null=True, blank=True)

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
                name="unique deletion for groups",
                fields=["deletion_type", "key", "group_type_index"],
            ),
        ]
        indexes = [models.Index(name="delete_verified_at index", fields=["delete_verified_at"])]
