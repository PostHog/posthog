from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Left

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UUIDModel

# Partial-unique "one active value per (team, account, definition)" constraint. Shared so the write
# service can tell this (retriable) race apart from other integrity errors by name.
ACTIVE_VALUE_CONSTRAINT_NAME = "unique_active_custom_property_value"

SORT_VALUE_STR_PREFIX_LENGTH = 256


def _active_sort_index(value_field: str, name: str, *, sort_expression: Left | None = None) -> models.Index:
    return models.Index(
        F("team"),
        F("definition"),
        sort_expression or F(value_field),
        F("account"),
        condition=Q(is_deleted=False, **{f"{value_field}__isnull": False}),
        name=name,
    )


class CustomPropertyValue(TeamScopedRootMixin, UUIDModel, CreatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
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
        indexes = [
            models.Index(
                fields=["team", "definition", "account"],
                condition=Q(is_deleted=False),
                name="cpv_active_team_definition_idx",
            ),
            _active_sort_index(
                "value_str",
                "cpv_active_sort_str_idx",
                sort_expression=Left("value_str", SORT_VALUE_STR_PREFIX_LENGTH),
            ),
            _active_sort_index("value_bool", "cpv_active_sort_bool_idx"),
            _active_sort_index("value_num", "cpv_active_sort_num_idx"),
            _active_sort_index("value_datetime", "cpv_active_sort_datetime_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "account", "definition"],
                condition=Q(is_deleted=False),
                name=ACTIVE_VALUE_CONSTRAINT_NAME,
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
