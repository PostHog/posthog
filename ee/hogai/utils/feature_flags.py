import posthoganalytics

from posthog.models import Team, User


def has_web_search_feature_flag(team: Team, user: User) -> bool:
    return posthoganalytics.feature_enabled(
        "phai-web-search",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def is_privacy_mode_enabled(team: Team) -> bool:
    """
    Check if privacy mode is enabled for a team's organization.
    """
    return posthoganalytics.feature_enabled(
        "phai-privacy-mode",
        str(team.organization_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_phai_tasks_feature_flag(team: Team, user: User) -> bool:
    return posthoganalytics.feature_enabled(
        "phai-tasks",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_task_tool_feature_flag(team: Team, user: User) -> bool:
    return posthoganalytics.feature_enabled(
        "phai-task-tool",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_upsert_dashboard_feature_flag(team: Team, user: User) -> bool:
    return posthoganalytics.feature_enabled(
        "phai-upsert-dashboards",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_error_tracking_mode_feature_flag(team: Team, user: User) -> bool:
    return posthoganalytics.feature_enabled(
        "posthog-ai-error-tracking-mode",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_memory_tool_feature_flag(team: Team, user: User) -> bool:
    return posthoganalytics.feature_enabled(
        "phai-memory-tool",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_create_form_tool_feature_flag(team: Team, user: User) -> bool:
    return posthoganalytics.feature_enabled(
        "phai-create-form-tool",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )
