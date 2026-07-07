from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class CustomPropertySource(TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )

    definition = models.OneToOneField(
        "customer_analytics.CustomPropertyDefinition", on_delete=models.CASCADE, related_name="source"
    )
    saved_query = models.ForeignKey(
        "data_modeling.DataWarehouseSavedQuery", on_delete=models.SET_NULL, null=True, related_name="+"
    )

    source_column = models.CharField(max_length=400)
    key_column = models.CharField(max_length=400)

    is_enabled = models.BooleanField(default=True)
    consecutive_failures = models.PositiveIntegerField(default=0)

    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.TextField(null=True, blank=True)
