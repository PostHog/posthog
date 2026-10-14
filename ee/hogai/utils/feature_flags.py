from typing import Literal, cast

import posthoganalytics

from posthog.models import Team, User
from posthog.ph_client import feature_enabled_or_false

from products.business_knowledge.backend.logic import has_feature_flag as bk_has_feature_flag

LlmGatewayVariant = Literal["control", "gateway-anthropic", "gateway-bedrock"]
_VALID_LLM_GATEWAY_VARIANTS: set[str] = {"control", "gateway-anthropic", "gateway-bedrock"}


def is_privacy_mode_enabled(team: Team) -> bool:
    """
    Check if privacy mode is enabled for a team's organization.
    """
    return feature_enabled_or_false(
        "phai-privacy-mode",
        str(team.organization_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_phai_tasks_feature_flag(team: Team, user: User) -> bool:
    return feature_enabled_or_false(
        "phai-tasks",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_task_tool_feature_flag(team: Team, user: User) -> bool:
    return feature_enabled_or_false(
        "phai-task-tool",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_conversation_topic_feature_flag(team: Team, user: User) -> bool:
    return feature_enabled_or_false(
        "posthog-ai-web-analytics-nudge",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_memory_tool_feature_flag(team: Team, user: User) -> bool:
    return feature_enabled_or_false(
        "phai-memory-tool",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_plan_mode_feature_flag(team: Team, user: User) -> bool:
    return feature_enabled_or_false(
        "phai-plan-mode",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_experiment_summary_tool_feature_flag(team: Team, user: User) -> bool:
    return feature_enabled_or_false(
        "experiment-ai-summary",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def is_core_memory_disabled(team: Team, user: User) -> bool:
    return feature_enabled_or_false(
        "phai-core-mem-disabled",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_mcp_gateway_feature_flag(team: Team, user: User) -> bool:
    return feature_enabled_or_false(
        "mcp-gateway",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_sandbox_mode_feature_flag(team: Team, user: User) -> bool:
    return feature_enabled_or_false(
        "phai-sandbox-mode",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_conversation_task_mirror_feature_flag(team: Team, user: User) -> bool:
    """Whether LangGraph conversations are mirrored into the task world after each turn."""
    return feature_enabled_or_false(
        "phai-conversation-task-mirror",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def has_customer_analytics_mode_feature_flag(team: Team, user: User) -> bool:
    return feature_enabled_or_false(
        "customer-analytics-csp",
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


def is_inkeep_docs_search_disabled(team: Team, distinct_id: str) -> bool:
    # docs-search then reads the PostHog docs business knowledge instead of Inkeep.
    # A team's own business knowledge stays on product-business-knowledge.
    return feature_enabled_or_false(
        "disable-inkeep-docs-search",
        distinct_id,
        groups={"organization": str(team.organization_id), "project": str(team.uuid)},
        send_feature_flag_events=False,
    )


def has_business_knowledge_feature_flag(team: Team) -> bool:
    # Canonical check lives in the owning product; kept as a delegate so existing
    # ee call sites and test patches don't move.
    return bk_has_feature_flag(team)
