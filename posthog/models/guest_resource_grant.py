from django.conf import settings
from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import UUIDModel


class GuestResourceGrant(ModelActivityMixin, UUIDModel):
    """Per-resource read grant attached to a guest membership.

    One row per (membership, team, resource, resource_id) the guest is allowed to see.
    Grants are the canonical record the middleware in PR #2 consults to decide whether
    a request may reach its viewset.

    ``resource_id`` is a ``CharField(36)`` to mirror the ``AccessControl.resource_id``
    convention — the grant stores whatever identifier the resource's URL uses: the
    stringified numeric PK for dashboards, the ``short_id`` for insights and
    notebooks. This lets the middleware match URL segments directly without
    integer casts or short_id lookup dances.

    Guests are meant to be created through an ``OrganizationInvite`` whose
    ``guest_resources`` JSON describes the intended grants; the invite-acceptance
    flow that converts those into rows here lives in PR #2. A pending grant
    (``is_pending=True``) is permitted to exist with ``organization_membership=NULL``
    to support future flows that pre-materialize rows before acceptance — the
    CHECK constraint enforces the XOR between pending/no-membership and
    active/with-membership.
    """

    activity_logging_on_delete = True

    class Resource(models.TextChoices):
        DASHBOARD = "dashboard", "Dashboard"
        INSIGHT = "insight", "Insight"
        NOTEBOOK = "notebook", "Notebook"

    organization_membership = models.ForeignKey(
        "posthog.OrganizationMembership",
        on_delete=models.CASCADE,
        null=True,
        related_name="guest_resource_grants",
    )
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    resource = models.CharField(max_length=32, choices=Resource.choices)
    resource_id = models.CharField(
        max_length=36,
        help_text=(
            "URL-style identifier for the granted object — stringified numeric PK for dashboards, "
            "short_id for insights and notebooks. Mirrors AccessControl.resource_id so the enforcement "
            "layer compares URL segments directly."
        ),
    )
    is_pending = models.BooleanField(
        default=False,
        help_text="True while the grant is attached to an unaccepted invite (no membership yet).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
    )

    class Meta:
        indexes = [
            models.Index(fields=["organization_membership", "team"]),
            models.Index(fields=["team", "resource", "resource_id"]),
        ]
        # Duplicate (membership, team, resource, resource_id) tuples are forbidden for active grants;
        # pending rows have membership=NULL so Postgres NULL-uniqueness keeps them out of this index.
        unique_together = [("organization_membership", "team", "resource", "resource_id")]
        # XOR: active grants (is_pending=False) require a membership; pending grants (is_pending=True)
        # must have no membership. Named after the rule it enforces.
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(is_pending=False, organization_membership__isnull=False)
                    | models.Q(is_pending=True, organization_membership__isnull=True)
                ),
                name="active_grants_need_membership",
            ),
        ]
