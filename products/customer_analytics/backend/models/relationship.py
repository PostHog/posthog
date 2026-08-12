from django.db import models
from django.db.models import Q
from django.utils import timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class AccountRelationshipDefinition(TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )

    name = models.CharField(max_length=400)
    description = models.TextField(
        null=True,
        blank=True,
        help_text="What this relationship means, e.g. 'The customer success manager responsible for this account'.",
    )
    is_single_holder = models.BooleanField(
        default=True,
        help_text="Whether only one user can hold this relationship per account at a time, e.g. a single CSM per account.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"],
                name="unique_relationship_definition_name",
            ),
        ]


class AccountRelationship(TeamScopedRootMixin, UUIDModel, CreatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    definition = models.ForeignKey(
        "customer_analytics.AccountRelationshipDefinition", on_delete=models.CASCADE, related_name="relationships"
    )
    account = models.ForeignKey("customer_analytics.Account", on_delete=models.CASCADE, related_name="relationships")
    user = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, db_constraint=False, related_name="+"
    )

    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["team", "account", "definition"],
                condition=Q(ended_at__isnull=True),
                name="idx_active_account_rel",
            ),
            models.Index(
                fields=["team", "user"],
                condition=Q(ended_at__isnull=True),
                name="idx_active_rel_by_user",
            ),
        ]
