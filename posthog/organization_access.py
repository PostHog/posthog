"""One definition of when an organization is closed to its members, and of what stays open.

`ActiveOrganizationMiddleware` and `ActiveOrganizationPermission` both read the answer from here,
so a page load and an API call cannot disagree.

`organizationLogic` holds its own copy of the page lists, because nothing imports across the two
trees. Change one and change the other. A stale copy there costs a client-side redirect the server
would not make, which the server-side check corrects on the next full page load.
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from posthog.models.organization import Organization


class OrganizationBlock(StrEnum):
    """Values double as the DRF error codes, so a caller can branch on the reason."""

    PENDING_DELETION = "organization_pending_deletion"
    DEACTIVATED = "organization_deactivated"


BLOCK_PAGES: dict[OrganizationBlock, str] = {
    OrganizationBlock.PENDING_DELETION: "/organization-pending-deletion",
    OrganizationBlock.DEACTIVATED: "/organization-deactivated",
}

# Pages that act on an organization other than the one the user is in, so no block of that
# organization reaches them. An invite link targets the *inviting* organization, whose own state
# `OrganizationInvite.validate` enforces on every accept path.
ORG_INDEPENDENT_PAGES: tuple[str, ...] = ("/signup/",)

# What a blocked organization's members keep, beyond the page that explains the block.
# Deactivation keeps billing, because settling the balance is how a member lifts it. No payment
# restores an organization that is pending deletion, so that state keeps nothing.
# `/billing/authorization_status` is the Stripe return route for a payment method that needs a
# redirect. Without it the payment lands on the block page and never confirms.
EXTRA_ALLOWED_PAGES: dict[OrganizationBlock, tuple[str, ...]] = {
    OrganizationBlock.PENDING_DELETION: (),
    OrganizationBlock.DEACTIVATED: ("/organization/billing", "/billing/authorization_status"),
}


def organization_block(organization: "Organization") -> Optional[OrganizationBlock]:
    """Why this organization is closed to its members, or None when it is open.

    Pending deletion is checked first because it is the stricter state, and an organization on its
    way out is often deactivated too.

    Only an explicit `False` deactivates. `is_active` is nullable, but the migration that added it
    backfilled every row to `True` and operators write `False` explicitly (see
    `OrganizationAdmin.bulk_deactivate_view`), so a null means "never deactivated".
    """
    if organization.is_pending_deletion:
        return OrganizationBlock.PENDING_DELETION
    if organization.is_active is False:
        return OrganizationBlock.DEACTIVATED
    return None


def page_is_allowed(block: OrganizationBlock, path: str) -> bool:
    """Paths in the lists are prefixes, each matching a route declared in `frontend/src/scenes/urls.ts`."""
    if path == BLOCK_PAGES[block]:
        return True
    if any(path.startswith(allowed) for allowed in ORG_INDEPENDENT_PAGES):
        return True
    return any(path.startswith(allowed) for allowed in EXTRA_ALLOWED_PAGES[block])


def block_invite_detail(block: OrganizationBlock) -> str:
    if block is OrganizationBlock.PENDING_DELETION:
        return (
            "This organization is scheduled for deletion, so you can't join it. "
            "Ask the person who invited you to contact support if it should be restored."
        )
    return (
        "This organization is deactivated, so you can't join it yet. Ask the person who invited you to contact support."
    )


def block_api_detail(block: OrganizationBlock, organization: "Organization") -> str:
    if block is OrganizationBlock.PENDING_DELETION:
        return (
            "This organization is scheduled for deletion. API access is blocked. "
            "Contact support if you need it restored."
        )
    reason = organization.is_not_active_reason
    # `reason` is operator text, already written to be shown to users.
    detail = f"This organization is deactivated. {reason.strip()}" if reason else "This organization is deactivated."
    return f"{detail} API access stays blocked until it's restored. Contact support if you think this is a mistake."
