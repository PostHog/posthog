"""
Module to centralize event reporting on the server-side.
"""

import posthoganalytics


def report_user_signed_up(
    distinct_id: str,
    is_instance_first_user: bool,
    is_organization_first_user: bool,
    new_onboarding_enabled: bool = False,
    backend_processor: str = "",  # which serializer/view processed the request
    login_provider: str = "",  # which third-party provider processed the login (empty = no third-party)
) -> None:

    props = {
        "is_first_user": is_instance_first_user,
        "is_organization_first_user": is_organization_first_user,
        "new_onboarding_enabled": new_onboarding_enabled,
        "signup_backend_processor": backend_processor,
        "login_provider": login_provider,
    }

    # TODO: This should be $set_once as user props.
    posthoganalytics.identify(distinct_id, props)
    posthoganalytics.capture(distinct_id, "user signed up", properties=props)
