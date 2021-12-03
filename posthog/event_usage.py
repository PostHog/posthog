"""
Module to centralize event reporting on the server-side.
"""

from typing import Any, Dict, List, Optional

import posthoganalytics

from posthog.models import Organization, User
from posthog.models.team import Team
from posthog.settings import SITE_URL
from posthog.utils import get_instance_realm


def report_user_signed_up(
    user: User,
    is_instance_first_user: bool,
    is_organization_first_user: bool,
    new_onboarding_enabled: bool = False,
    backend_processor: str = "",  # which serializer/view processed the request
    social_provider: str = "",  # which third-party provider processed the login (empty = no third-party)
    user_analytics_metadata: Optional[dict] = None,  # analytics metadata taken from the User object
    org_analytics_metadata: Optional[dict] = None,  # analytics metadata taken from the Organization object
) -> None:
    """
    Reports that a new user has joined. Only triggered when a new user is actually created (i.e. when an existing user
    joins a new organization, this event is **not** triggered; see `report_user_joined_organization`).
    """

    props = {
        "is_first_user": is_instance_first_user,
        "is_organization_first_user": is_organization_first_user,
        "new_onboarding_enabled": new_onboarding_enabled,
        "signup_backend_processor": backend_processor,
        "signup_social_provider": social_provider,
        "realm": get_instance_realm(),
    }
    if user_analytics_metadata is not None:
        props.update(user_analytics_metadata)

    if org_analytics_metadata is not None:
        for k, v in org_analytics_metadata.items():
            props[f"org__{k}"] = v

    # TODO: This should be $set_once as user props.
    posthoganalytics.identify(user.distinct_id, props)
    posthoganalytics.capture(
        user.distinct_id, "user signed up", properties=props, groups=groups(user.organization, user.team),
    )


def report_user_joined_organization(organization: Organization, current_user: User) -> None:
    """
    Triggered after an already existing user joins an already existing organization.
    """
    posthoganalytics.capture(
        current_user.distinct_id,
        "user joined organization",
        properties={
            "organization_id": str(organization.id),
            "user_number_of_org_membership": current_user.organization_memberships.count(),
            "org_current_invite_count": organization.active_invites.count(),
            "org_current_project_count": organization.teams.count(),
            "org_current_members_count": organization.memberships.count(),
        },
        groups=groups(organization),
    )


def report_user_logged_in(
    user: User, social_provider: str = "",  # which third-party provider processed the login (empty = no third-party)
) -> None:
    """
    Reports that a user has logged in to PostHog.
    """
    posthoganalytics.capture(
        user.distinct_id,
        "user logged in",
        properties={"social_provider": social_provider},
        groups=groups(user.current_organization, user.current_team),
    )


def report_onboarding_completed(organization: Organization, current_user: User) -> None:
    """
    Reports that the `new-onboarding-2822` has been completed.
    """

    team_members_count = organization.members.count()

    # TODO: This should be $set_once as user props.
    posthoganalytics.identify(current_user.distinct_id, {"onboarding_completed": True})
    posthoganalytics.capture(
        current_user.distinct_id,
        "onboarding completed",
        properties={"team_members_count": team_members_count},
        groups=groups(organization, current_user.current_team),
    )


def report_user_updated(user: User, updated_attrs: List[str]) -> None:
    """
    Reports a user has been updated. This includes current_team, current_organization & password.
    """

    updated_attrs.sort()
    posthoganalytics.capture(
        user.distinct_id,
        "user updated",
        properties={"updated_attrs": updated_attrs},
        groups=groups(user.current_organization, user.current_team),
    )


def report_user_password_reset(user: User) -> None:
    """
    Reports a user resetting their password.
    """
    posthoganalytics.capture(
        user.distinct_id, "user password reset", groups=groups(user.current_organization, user.current_team)
    )


def report_team_member_invited(
    user: User, name_provided: bool, current_invite_count: int, current_member_count: int, email_available: bool,
) -> None:
    """
    Triggered after a user creates an **individual** invite for a new team member. See `report_bulk_invited`
    for bulk invite creation.
    """
    posthoganalytics.capture(
        user.distinct_id,
        "team invite executed",
        properties={
            "name_provided": name_provided,
            "current_invite_count": current_invite_count,  # number of invites including this one
            "current_member_count": current_member_count,
            "email_available": email_available,
        },
        groups=groups(user.current_organization, user.current_team),
    )


def report_bulk_invited(
    user: User,
    invitee_count: int,
    name_count: int,
    current_invite_count: int,
    current_member_count: int,
    email_available: bool,
) -> None:
    """
    Triggered after a user bulk creates invites for another user.
    """
    posthoganalytics.capture(
        user.distinct_id,
        "bulk invite executed",
        properties={
            "invitee_count": invitee_count,
            "name_count": name_count,
            "current_invite_count": current_invite_count,  # number of invites including this set
            "current_member_count": current_member_count,
            "email_available": email_available,
        },
        groups=groups(user.current_organization, user.current_team),
    )


def report_org_usage(organization_id: str, distinct_id: str, properties: Dict[str, Any]) -> None:
    """
    Triggered daily by Celery scheduler.
    """
    posthoganalytics.capture(
        distinct_id,
        "organization usage report",
        properties,
        groups={"organization": organization_id, "instance": SITE_URL},
    )
    posthoganalytics.group_identify("organization", organization_id, properties)


def report_org_usage_failure(organization_id: str, distinct_id: str, err: str) -> None:
    posthoganalytics.capture(
        distinct_id,
        "organization usage report failure",
        properties={"error": err,},
        groups={"organization": organization_id, "instance": SITE_URL},
    )


def report_user_action(user: User, event: str, properties: Dict = {}):
    posthoganalytics.capture(
        user.distinct_id, event, properties=properties, groups=groups(user.current_organization, user.current_team),
    )


def report_organization_deleted(user: User, organization: Organization):
    posthoganalytics.capture(
        user.distinct_id, "organization deleted", organization.get_analytics_metadata(), groups=groups(organization)
    )


def groups(organization: Optional[Organization] = None, team: Optional[Team] = None):
    result = {"instance": SITE_URL}
    if organization is not None:
        result["organization"] = str(organization.pk)
    if team is not None:
        result["project"] = str(team.uuid)
    return result
