from collections.abc import Callable
from typing import Optional

import posthoganalytics

# A recorded classification meaning "nothing owned this resource". It is distinct from NULL,
# which means no classification was recorded at all: a request created before the column
# existed, or an action that does not classify ownership. Those must still apply.
OWNER_KIND_UNOWNED = "unowned"


def owner_kind_changed(recorded: Optional[str], current: Optional[str]) -> bool:
    """Whether the owner recorded when a change request was created still holds.

    An absent classification on either side is not a change. That keeps requests created
    before the column existed applying exactly as they did, and leaves actions that do not
    classify ownership unaffected.
    """
    if recorded is None or current is None:
        return False
    return recorded != current


# Narrowing removes approval coverage from about 72% of production flags, so it rolls out per
# organization rather than all at once. Off, every family behaves as it did before narrowing:
# `feature_flag.*` covers every flag and the owner-scoped families match nothing.
SCOPE_BY_OWNER_FLAG = "approvals-scope-by-flag-owner"


def scope_by_owner_enabled(organization) -> bool:
    """Whether this organization evaluates approval policies by which product owns the flag.

    Unresolvable reads as off. The off state is the wider one — every flag keeps the coverage it
    has today — so a flag lookup that fails locally costs coverage nothing.
    """
    if organization is None:
        return False
    return (
        posthoganalytics.feature_enabled(
            SCOPE_BY_OWNER_FLAG,
            f"org-{organization.id}",
            groups={"organization": str(organization.id)},
            group_properties={"organization": {"id": str(organization.id)}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
        is True
    )


def owner_in_scope(owner_scope: Optional[str], organization, derive_owner_kind: Callable[[], Optional[str]]) -> bool:
    """Whether a family scoped to `owner_scope` governs this flag.

    `owner_scope` is the product a family covers, or None for the family that covers the flags no
    product owns. `derive_owner_kind` reports which product owns this flag, None when none does.
    A reference is not ownership, so a flag a survey merely links to derives as unowned and stays
    with the unowned family.

    Before narrowing, the unowned family covers every flag and every owner-scoped family covers
    none. That is what keeps this change inert until an organization is rolled out.

    The owner arrives as a callable because deriving it reads every owning relation. An
    organization that is not rolled out must not pay for a classification that cannot change
    the answer.
    """
    if not scope_by_owner_enabled(organization):
        return owner_scope is None
    return derive_owner_kind() == owner_scope
