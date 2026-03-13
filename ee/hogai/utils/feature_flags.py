import posthoganalytics

from posthog.models import Team, User


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


def has_memory_tool_feature_flag(team: Team, user: User) -> bool:
    return posthoganalytics.feature_enabled(
        "phai-memory-tool",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_plan_mode_feature_flag(team: Team, user: User) -> bool:
    return posthoganalytics.feature_enabled(
        "phai-plan-mode",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_experiment_summary_tool_feature_flag(team: Team, user: User) -> bool:
    return posthoganalytics.feature_enabled(
        "experiment-ai-summary",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def is_core_memory_disabled(team: Team, user: User) -> bool:
    return posthoganalytics.feature_enabled(
        "phai-core-mem-disabled",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_mcp_servers_feature_flag(team: Team, user: User) -> bool:
    return posthoganalytics.feature_enabled(
        "mcp-servers",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_sandbox_mode_feature_flag(team: Team, user: User) -> bool:
    return posthoganalytics.feature_enabled(
        "phai-sandbox-mode",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )
