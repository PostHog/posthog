"""Whether an organization switched email verification off.

Split out of `posthog.api.email_verification`, which reaches the Celery email
tasks through its own imports. Modules that load before those tasks cannot import
that one, and asking this question needs none of it.

`posthog.api.email_verification` re-exports both names, so callers there keep
importing from where they already do.
"""

from typing import TYPE_CHECKING

from posthog.ph_client import feature_enabled_or_false

if TYPE_CHECKING:
    from posthog.models.user import User

VERIFICATION_DISABLED_FLAG = "email-verification-disabled"


def is_email_verification_disabled(user: "User") -> bool:
    # using disabled here so that the default state (if no flag exists) is that verification defaults to ON.
    return user.organization is not None and feature_enabled_or_false(
        VERIFICATION_DISABLED_FLAG,
        str(user.organization.id),
        groups={"organization": str(user.organization.id)},
        group_properties={"organization": {"id": str(user.organization.id)}},
    )
