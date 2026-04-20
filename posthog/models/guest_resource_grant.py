from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import UUIDTModel


class GuestResourceGrant(ModelActivityMixin, UUIDTModel):
    """Per-resource grant for a guest user. A guest has one row per (team, resource, resource_id)
    they are permitted to read. Grants are created either pending (attached to an invite) or
    active (attached to an accepted membership); flipping `is_pending` on invite acceptance
    avoids needing a separate pending-grants table.

    Enforcement of these grants lives in the access-control layer and a dedicated middleware,
    both landing in PR #2. This PR #1 only defines the shape.
    """

    # Enable delete-activity logging (ModelActivityMixin default is create/update only)
    activity_logging_on_delete = True

    class Resource(models.TextChoices):
        DASHBOARD = "dashboard"
        INSIGHT = "insight"
        NOTEBOOK = "notebook"

    organization_membership = models.ForeignKey(
        "posthog.OrganizationMembership",
        on_delete=models.CASCADE,
        null=True,
        related_name="guest_resource_grants",
        db_index=True,
    )
    invite = models.ForeignKey(
        "posthog.OrganizationInvite",
        on_delete=models.CASCADE,
        null=True,
        related_name="guest_resource_grants",
        db_index=True,
    )

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_index=True)
    resource = models.CharField(max_length=32, choices=Resource.choices)
    resource_id = models.CharField(max_length=36)
    """URL-style identifier for the granted object. Stringified numeric PK for dashboards,
    `short_id` for insights and notebooks — whatever shape the resource's own URL uses.
    Mirrors the `AccessControl.resource_id` convention (also a CharField), so the middleware
    and AC short-circuit can compare the URL segment as-is without integer casts or
    short_id lookup dances.
    """

    is_pending = models.BooleanField(default=True, db_index=True)
    """True while the grant is attached to an unaccepted invite. Flips to False when the invite
    is accepted and the grant is re-bound to the created OrganizationMembership. Stored
    explicitly (rather than derived from which FK is set) so queries that want active grants
    can filter on a single indexed column.
    """

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["team", "resource", "resource_id"],
                name="guest_grant_team_resource_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization_membership", "team", "resource", "resource_id"],
                condition=models.Q(organization_membership__isnull=False),
                name="unique_active_guest_grant",
            ),
            models.UniqueConstraint(
                fields=["invite", "team", "resource", "resource_id"],
                condition=models.Q(invite__isnull=False),
                name="unique_pending_guest_grant",
            ),
            models.CheckConstraint(
                check=(
                    models.Q(organization_membership__isnull=False, invite__isnull=True, is_pending=False)
                    | models.Q(organization_membership__isnull=True, invite__isnull=False, is_pending=True)
                ),
                name="guest_grant_state_consistent",
            ),
        ]
