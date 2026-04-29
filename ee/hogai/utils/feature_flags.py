from typing import Literal, cast

import posthoganalytics

from posthog.models import Team, User

LlmGatewayVariant = Literal["control", "gateway-anthropic", "gateway-bedrock"]
_VALID_LLM_GATEWAY_VARIANTS: set[str] = {"control", "gateway-anthropic", "gateway-bedrock"}


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


def get_llm_gateway_variant(team: Team, user: User) -> LlmGatewayVariant:
    variant = cast(
        "str | bool | None",
        posthoganalytics.get_feature_flag(
            "phai-llm-gateway-v2",
            str(user.distinct_id),
            groups={"organization": str(team.organization_id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
            send_feature_flag_events=False,
        ),
    )
    if isinstance(variant, str) and variant in _VALID_LLM_GATEWAY_VARIANTS:
        return cast("LlmGatewayVariant", variant)
    return "control"
