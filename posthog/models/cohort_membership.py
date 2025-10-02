from django.db import models

from posthog.models.utils import RootTeamMixin


class CohortMembership(RootTeamMixin, models.Model):
    """
    Model to track cohort membership changes for point-lookups.
    This model tracks when a person is added to or removed from a cohort.
    For high-load scenarios, we use soft deletes to avoid expensive hard deletes &
    no uniqueness constraints for the same reason.
    """

    id = models.BigAutoField(primary_key=True)

    # Core fields - no FK constraints for performance
    person_id = models.BigIntegerField(db_index=True)
    cohort_id = models.BigIntegerField(db_index=True)
    team_id = models.BigIntegerField(db_index=True)

    # Soft delete flag for performance - avoids expensive hard deletes
    is_deleted = models.BooleanField(default=False, db_index=True)

    class Meta:
        indexes = [
            # Primary lookup index for checking membership
            models.Index(fields=["person_id", "team_id", "cohort_id", "is_deleted"], name="cohort_membership_lookup"),
        ]

    def __str__(self) -> str:
        if self.is_deleted:
            return f"Person {self.person_id} not in Cohort {self.cohort_id}"
        else:
            return f"Person {self.person_id} in Cohort {self.cohort_id}"
