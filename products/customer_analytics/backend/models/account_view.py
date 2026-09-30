from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.customer_analytics.backend.facade.enums import AccountViewVisibility


class AccountView(ModelActivityMixin, TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    name = models.CharField(max_length=400)
    visibility = models.CharField(
        max_length=16,
        choices=AccountViewVisibility.choices,
        default=AccountViewVisibility.PRIVATE,
    )
    content = models.JSONField()
    text_content = models.TextField(default="", db_default="")
    version = models.PositiveIntegerField(default=1, db_default=1)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    last_modified_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["team", "deleted_at", "visibility"],
                name="ca_account_view_list_idx",
            ),
            models.Index(
                fields=["team", "created_by", "deleted_at"],
                name="ca_account_view_owner_idx",
            ),
        ]
