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
    # Account-target sources read from a materialized view (saved_query); person-target sources
    # bind to a raw incremental warehouse table (external_data_schema). Exactly one is set — the
    # facade enforces this, so no DB check constraint.
    saved_query = models.ForeignKey(
        "data_modeling.DataWarehouseSavedQuery", on_delete=models.SET_NULL, null=True, related_name="+"
    )
    external_data_schema = models.ForeignKey(
        "warehouse_sources.ExternalDataSchema",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        db_constraint=False,
    )

    # Account path: single view column -> the definition's value.
    source_column = models.CharField(max_length=400, null=True, blank=True)
    key_column = models.CharField(max_length=400)
    # Person path: {warehouse_column: person_property_name} for the columns this source maps.
    column_property_map = models.JSONField(null=True, blank=True, default=None)

    is_enabled = models.BooleanField(default=True)
    consecutive_failures = models.PositiveIntegerField(default=0)

    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.TextField(null=True, blank=True)
