from django.conf import settings
from django.db import models
from django.utils import timezone

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import DeletedMetaFields, UUIDTModel


class DataWarehouseExpression(ModelActivityMixin, TeamScopedRootMixin, UUIDTModel, DeletedMetaFields):
    """A saved HogQL expression exposed as a virtual field on a table.

    The expression is injected into the team's HogQL database on every build, so the
    field is available in all SQL queries. It can never shadow an existing field:
    injection skips names already present on the table.
    """

    # db_constraint=False on the hot-table FKs (team, created_by) so CreateModel takes no lock
    # on posthog_team / posthog_user; app-level enforcement is enough here.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    table_name = models.CharField(max_length=400)
    field_name = models.CharField(max_length=400)
    expression = models.TextField()

    def soft_delete(self) -> None:
        self.deleted = True
        self.deleted_at = timezone.now()
        self.save()
