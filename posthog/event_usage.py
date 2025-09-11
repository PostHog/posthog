"""
Module to centralize event reporting on the server-side.
"""

from typing import Optional

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
    role_at_organization: str = "",  # select input to ask what the user role is at the org
    referral_source: str = "",  # free text input to ask users where did they hear about us
) -> None:
    """
    Reports that a new user has joined. Only triggered when a new user is actually created (i.e. when an existing user
    joins a new organization, this event is **not** triggered; see `report_user_joined_organization`).
    """
    if not user.distinct_id:
        return

    props = {
        "is_first_user": is_instance_first_user,
        "is_organization_first_user": is_organization_first_user,
        "new_onboarding_enabled": new_onboarding_enabled,
        "signup_backend_processor": backend_processor,
        "signup_social_provider": social_provider,
        "realm": get_instance_realm(),
        "role_at_organization": role_at_organization,
        "referral_source": referral_source,
        "is_email_verified": user.is_email_verified,
    }
    if user_analytics_metadata is not None:
        props.update(user_analytics_metadata)

    if org_analytics_metadata is not None:
        for k, v in org_analytics_metadata.items():
            props[f"org__{k}"] = v

    props = {**props, "$set": {**props, **user.get_analytics_metadata()}}
    posthoganalytics.capture(
        distinct_id=user.distinct_id,
        event="user signed up",
        properties=props,
        groups=groups(user.organization, user.team),
    )


def report_user_verified_email(current_user: User) -> None:
    """
    Triggered after a user verifies their email address.
    """
    if not current_user.distinct_id:
        return

    posthoganalytics.capture(
        distinct_id=current_user.distinct_id,
        event="user verified email",
        properties={
            "$set": current_user.get_analytics_metadata(),
        },
    )


def alias_invite_id(user: User, invite_id: str) -> None:
    if not user.distinct_id:
        return

    posthoganalytics.alias(user.distinct_id, f"invite_{invite_id}")


def report_user_joined_organization(organization: Organization, current_user: User) -> None:
    """
    Triggered after an already existing user joins an already existing organization.
    """
    if not current_user.distinct_id:
        return

    posthoganalytics.capture(
        distinct_id=current_user.distinct_id,
        event="user joined organization",
        properties={
            "organization_id": str(organization.id),
            "user_number_of_org_membership": current_user.organization_memberships.count(),
            "org_current_invite_count": organization.active_invites.count(),
            "org_current_project_count": organization.teams.count(),
            "org_current_members_count": organization.memberships.count(),
            "$set": current_user.get_analytics_metadata(),
        },
        groups=groups(organization),
    )


def report_user_logged_in(
    user: User,
    social_provider: str = "",  # which third-party provider processed the login (empty = no third-party)
) -> None:
    """
    Reports that a user has logged in to PostHog.
    """
    if not user.distinct_id:
        return

    posthoganalytics.capture(
        distinct_id=user.distinct_id,
        event="user logged in",
        properties={"social_provider": social_provider},
        groups=groups(user.current_organization, user.current_team),
    )


def report_user_updated(user: User, updated_attrs: list[str]) -> None:
    """
    Reports a user has been updated. This includes current_team, current_organization & password.
    """
    if not user.distinct_id:
        return

    updated_attrs.sort()
    posthoganalytics.capture(
        distinct_id=user.distinct_id,
        event="user updated",
        properties={"updated_attrs": updated_attrs, "$set": user.get_analytics_metadata()},
        groups=groups(user.current_organization, user.current_team),
    )


def report_user_password_reset(user: User) -> None:
    """
    Reports a user resetting their password.
    """
    if not user.distinct_id:
        return

    posthoganalytics.capture(
        distinct_id=user.distinct_id,
        event="user password reset",
        groups=groups(user.current_organization, user.current_team),
    )


def report_team_member_invited(
    inviting_user: User,
    invite_id: str,
    name_provided: bool,
    current_invite_count: int,
    current_member_count: int,
    is_bulk: bool,
    email_available: bool,
    current_url: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """
    Triggered after a user creates an **individual** invite for a new team member. See `report_bulk_invited`
    for bulk invite creation.
    """

    properties = {
        "name_provided": name_provided,
        "current_invite_count": current_invite_count,  # number of invites including this one
        "current_member_count": current_member_count,
        "email_available": email_available,
        "is_bulk": is_bulk,
    }

    inviting_user_properties = {
        **properties,
        "$current_url": current_url,
        "$session_id": session_id,
    }

    # Report for inviting user
    if inviting_user.distinct_id:
        posthoganalytics.capture(
            distinct_id=inviting_user.distinct_id,
            event="team member invited",
            properties=inviting_user_properties,
            groups=groups(inviting_user.current_organization, inviting_user.current_team),
        )

    # Report for invitee
    posthoganalytics.capture(
        distinct_id=f"invite_{invite_id}",  # see `alias_invite_id` too
        event="user invited",
        properties=properties,
        groups=groups(inviting_user.current_organization, None),
    )


def report_bulk_invited(
    user: User,
    invitee_count: int,
    name_count: int,
    current_invite_count: int,
    current_member_count: int,
    email_available: bool,
    current_url: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """
    Triggered after a user bulk creates invites for another user.
    """
    if not user.distinct_id:
        return

    posthoganalytics.capture(
        distinct_id=user.distinct_id,
        event="bulk invite executed",
        properties={
            "invitee_count": invitee_count,
            "name_count": name_count,
            "current_invite_count": current_invite_count,  # number of invites including this set
            "current_member_count": current_member_count,
            "email_available": email_available,
            "$current_url": current_url,
            "$session_id": session_id,
        },
        groups=groups(user.current_organization, user.current_team),
    )


def report_user_organization_membership_level_changed(
    user: User,
    organization: Organization,
    new_level: int,
    previous_level: int,
) -> None:
    """
    Triggered after a user's membership level in an organization is changed.
    """
    if not user.distinct_id:
        return
    posthoganalytics.capture(
        distinct_id=user.distinct_id,
        event="membership level changed",
        properties={
            "new_level": new_level,
            "previous_level": previous_level,
            "$set": user.get_analytics_metadata(),
        },
        groups=groups(organization),
    )


def report_user_action(user: User, event: str, properties: Optional[dict] = None, team: Optional[Team] = None):
    if not user.distinct_id:
        return
    if properties is None:
        properties = {}
    posthoganalytics.capture(
        distinct_id=user.distinct_id,
        event=event,
        properties=properties,
        groups=groups(user.current_organization, team or user.current_team),
    )


def report_organization_deleted(user: User, organization: Organization):
    if not user.distinct_id:
        return
    posthoganalytics.capture(
        distinct_id=user.distinct_id,
        event="organization deleted",
        properties=organization.get_analytics_metadata(),
        groups=groups(organization),
    )


def groups(organization: Optional[Organization] = None, team: Optional[Team] = None):
    result = {"instance": SITE_URL}
    if organization is not None:
        result["organization"] = str(organization.pk)
        if organization.customer_id:
            result["customer"] = organization.customer_id
    elif team is not None and team.organization_id:
        result["organization"] = str(team.organization_id)

    if team is not None:
        result["project"] = str(team.uuid)
    return result


def report_team_action(
    team: Team,
    event: str,
    properties: Optional[dict] = None,
    group_properties: Optional[dict] = None,
):
    """
    For capturing events where it is unclear which user was the core actor we can use the team instead
    """
    if properties is None:
        properties = {}
    posthoganalytics.capture(distinct_id=str(team.uuid), event=event, properties=properties, groups=groups(team=team))

    if group_properties:
        posthoganalytics.group_identify("team", str(team.id), properties=group_properties)


def report_organization_action(
    organization: Organization,
    event: str,
    properties: Optional[dict] = None,
    group_properties: Optional[dict] = None,
):
    """
    For capturing events where it is unclear which user was the core actor we can use the organization instead
    """
    if properties is None:
        properties = {}
    posthoganalytics.capture(
        distinct_id=str(organization.id),
        event=event,
        properties=properties,
        groups=groups(organization=organization),
    )

    if group_properties:
        posthoganalytics.group_identify("organization", str(organization.id), properties=group_properties)
