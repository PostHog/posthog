from django.db import models
from django.db.models import Q
from django.utils import timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

from products.customer_analytics.backend.facade.enums import AccountRelationshipSource


class AccountRelationshipDefinition(TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
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
    is_controlled = models.BooleanField(
        default=False,
        db_default=False,
        help_text=(
            "Whether customer analytics can take control of this relationship per account. Rows under a controlled "
            "definition cannot be deleted. On an account where control has started, only a person can change the "
            "relationship and an empty relationship is a deliberate decision."
        ),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"],
                name="unique_relationship_definition_name",
            ),
        ]


class AccountRelationship(TeamScopedRootMixin, UUIDModel, CreatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
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

    source = models.CharField(max_length=32, choices=AccountRelationshipSource.choices, null=True, blank=True)
    # The id of the external record that decided this row, when an integration wrote it (for a
    # Salesforce claim, the Task id). Unique per team and source, so an integration that reads the
    # same record again finds this row, ended or not, instead of writing a second one.
    source_ref = models.CharField(max_length=400, null=True, blank=True)

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
        constraints = [
            models.UniqueConstraint(
                fields=["team", "source", "source_ref"],
                name="unique_relationship_per_source_ref",
            ),
        ]


class AccountRelationshipControl(TeamScopedRootMixin, UUIDModel, CreatedMetaFields):
    """Customer analytics holds authority over one controlled relationship on one account.

    The row exists from enrollment on; its absence means the relationship is unmanaged there, whatever
    the relationship rows say. ``controlled_at`` is the enrollment or the last decision a person took on
    the relationship here, and it is the fence an automated claim must be newer than. Automated writers
    never move it.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    account = models.ForeignKey(
        "customer_analytics.Account", on_delete=models.CASCADE, related_name="relationship_controls"
    )
    # RESTRICT keeps a controlled definition deletable only once no account is enrolled under it,
    # while a team deletion still cascades through both rows.
    definition = models.ForeignKey(
        "customer_analytics.AccountRelationshipDefinition", on_delete=models.RESTRICT, related_name="controls"
    )
    controlled_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "account", "definition"],
                name="unique_relationship_control_per_account",
            ),
        ]
