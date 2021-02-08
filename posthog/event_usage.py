"""
Module to centralize event reporting on the server-side.
"""

import posthoganalytics

from posthog.models import Organization, User


def report_user_signed_up(
    distinct_id: str,
    is_instance_first_user: bool,
    is_organization_first_user: bool,
    new_onboarding_enabled: bool = False,
    backend_processor: str = "",  # which serializer/view processed the request
    social_provider: str = "",  # which third-party provider processed the login (empty = no third-party)
) -> None:

    props = {
        "is_first_user": is_instance_first_user,
        "is_organization_first_user": is_organization_first_user,
        "new_onboarding_enabled": new_onboarding_enabled,
        "signup_backend_processor": backend_processor,
        "social_provider": social_provider,
    }

    # TODO: This should be $set_once as user props.
    posthoganalytics.identify(distinct_id, props)
    posthoganalytics.capture(distinct_id, "user signed up", properties=props)


def report_onboarding_completed(organization: Organization, current_user: User) -> None:
    """
    Reports that the `new-onboarding-2822` has been completed.
    """

    team_members_count = organization.members.count()

    # TODO: This should be $set_once as user props.
    posthoganalytics.identify(current_user.distinct_id, {"onboarding_completed": True})
    posthoganalytics.capture(
        current_user.distinct_id, "onboarding completed", properties={"team_members_count": team_members_count},
    )


def report_bulk_invited(
    distinct_id: str,
    invitee_count: int,
    name_count: int,
    current_invite_count: int,
    current_member_count: int,
    email_available: bool,
) -> None:
    posthoganalytics.capture(
        distinct_id,
        "bulk invite executed",
        properties={
            "invitee_count": invitee_count,
            "name_count": name_count,
            "current_invite_count": current_invite_count,
            "current_member_count": current_member_count,
            "email_available": email_available,
        },
    )
