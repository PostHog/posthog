"""Organization-wide billing policy; credential restrictions stay at the request boundary."""

from posthog.exceptions_capture import capture_exception
from posthog.models import Organization, OrganizationMembership, User

from ..facade.enums import Action

BILLING_ACTIONS = frozenset({Action.VIEW, Action.EDIT, Action.VIEW_USAGE})


def _flag(user: User, organization: Organization, key: str) -> bool | None:
    # Permissions imports the SDK during Django startup.
    from posthog.permissions import posthog_feature_flag_enabled  # noqa: PLC0415

    if not user.distinct_id:
        return None
    try:
        return posthog_feature_flag_enabled(key, str(user.distinct_id), organization_id=organization.id)
    except Exception as error:
        capture_exception(error, {"organization_id": organization.id, "flag": key})
        return None


def billing_actions(user: User, organization: Organization, level: int) -> frozenset[Action]:
    if level >= OrganizationMembership.Level.OWNER:
        return BILLING_ACTIONS
    if level < OrganizationMembership.Level.MEMBER:
        return frozenset()
    if _flag(user, organization, "owner-only-billing") is not False:
        return frozenset()
    if level >= OrganizationMembership.Level.ADMIN:
        return BILLING_ACTIONS
    if _flag(user, organization, "member-billing-usage-spend-read-access") is True:
        return frozenset({Action.VIEW_USAGE})
    return frozenset()
