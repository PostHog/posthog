from django.db import models
from django.db.models import Q

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UUIDModel


class CustomPropertyValue(TeamScopedRootMixin, UUIDModel, CreatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    definition = models.ForeignKey(
        "customer_analytics.CustomPropertyDefinition", on_delete=models.CASCADE, related_name="values"
    )
    account = models.ForeignKey(
        "customer_analytics.Account", on_delete=models.CASCADE, related_name="custom_property_values"
    )

    # Rows are append-only so the value's history can be analyzed; superseded values are soft-deleted
    # rather than overwritten, leaving at most one active row per (team, account, definition).
    is_deleted = models.BooleanField(default=False)

    value_str = models.TextField(null=True, blank=True)
    value_bool = models.BooleanField(null=True, blank=True)
    value_num = models.FloatField(null=True, blank=True)
    value_datetime = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "account", "definition"],
                condition=Q(is_deleted=False),
                name="unique_active_custom_property_value",
            ),
            models.CheckConstraint(
                name="custom_property_value_exactly_one_value",
                condition=(
                    Q(
                        value_str__isnull=False,
                        value_bool__isnull=True,
                        value_num__isnull=True,
                        value_datetime__isnull=True,
                    )
                    | Q(
                        value_str__isnull=True,
                        value_bool__isnull=False,
                        value_num__isnull=True,
                        value_datetime__isnull=True,
                    )
                    | Q(
                        value_str__isnull=True,
                        value_bool__isnull=True,
                        value_num__isnull=False,
                        value_datetime__isnull=True,
                    )
                    | Q(
                        value_str__isnull=True,
                        value_bool__isnull=True,
                        value_num__isnull=True,
                        value_datetime__isnull=False,
                    )
                ),
            ),
        ]
