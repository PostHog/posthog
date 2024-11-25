from django.db import models


# This table is responsible for mapping between group types for a Team/Project and event columns
# to add group keys
class GroupTypeMapping(models.Model):
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    project = models.ForeignKey("Project", on_delete=models.CASCADE)
    group_type = models.CharField(max_length=400, null=False, blank=False)
    group_type_index = models.IntegerField(null=False, blank=False)
    # Used to display in UI
    name_singular = models.CharField(max_length=400, null=True, blank=True)
    name_plural = models.CharField(max_length=400, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("project", "group_type"),
                name="posthog_group_type_proj_idx",
            ),
            models.Index(
                fields=("project", "group_type_index"),
                name="posthog_group_type_i_proj_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(fields=("project", "group_type"), name="unique group types for project"),
            models.UniqueConstraint(
                fields=("project", "group_type_index"), name="unique event column indexes for project"
            ),
            models.CheckConstraint(
                check=models.Q(group_type_index__lte=5),
                name="group_type_index is less than or equal 5",
            ),
            models.CheckConstraint(
                name="group_type_project_id_is_not_null",
                # We have this as a constraint rather than IS NOT NULL on the field, because setting IS NOT NULL cannot
                # be done without locking the table. By adding this constraint using Postgres's `NOT VALID` option
                # (via Django `AddConstraintNotValid()`) and subsequent `VALIDATE CONSTRAINT`, we avoid locking.
                check=models.Q(project_id__isnull=False),
            ),
        ]
