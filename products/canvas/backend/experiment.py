"""Who is in the canvas experiment, and what the experiment takes away from them."""

from typing import Any

import structlog

from posthog.models import Team, User
from posthog.ph_client import feature_enabled_or_false

from products.today.backend.facade import api as today_api

logger = structlog.get_logger(__name__)

CANVAS_EXPERIMENT_FLAG = "canvas-experiment"

# Experiment users create and edit canvases through MCP, so the web app's own create, edit,
# hosted generation and agent paths are closed to them. Only session callers are restricted:
# MCP clients, PostHog Desktop, scouts, sandboxes and workload tokens never use a session.
EXPERIMENT_SESSION_BLOCKED_ACTIONS = frozenset(
    {
        "create",
        "publish",
        "edit",
        "draft",
        "promote",
        "revert",
        "publish_current_version",
        "publish_layout",
        "patch_layout",
        "request_fix",
        "request_agent",
    }
)
# Linking a generation task is how the web app starts a hosted generation or a hosted edit run.
EXPERIMENT_SESSION_BLOCKED_UPDATE_FIELDS = frozenset({"generation_task_id"})
# A retry queues a build whose completion can publish content the web app could not publish itself.
# The other build actions (pin, unpin, cancel) do not publish anything.
EXPERIMENT_SESSION_BLOCKED_BUILD_ACTIONS = frozenset({"retry"})


def in_canvas_experiment(user: User, team: Team) -> bool:
    """Whether this person is in the canvas experiment. The experiment needs the new navigation too. Fails closed."""
    return _canvas_experiment_flag_on(user, team) and today_api.is_enabled_for(user, team)


def blocks_session_action(action: str | None, data: Any) -> bool:
    """Whether a web app session may not run this viewset action while the experiment is on for it."""
    if action in EXPERIMENT_SESSION_BLOCKED_ACTIONS:
        return True
    if action == "partial_update" and isinstance(data, dict):
        return not EXPERIMENT_SESSION_BLOCKED_UPDATE_FIELDS.isdisjoint(data)
    if action == "build_action" and isinstance(data, dict):
        # The body is not validated yet, and an unhashable value would raise on the membership check.
        build_action = data.get("action")
        return isinstance(build_action, str) and build_action in EXPERIMENT_SESSION_BLOCKED_BUILD_ACTIONS
    return False


def _canvas_experiment_flag_on(user: User, team: Team) -> bool:
    try:
        return feature_enabled_or_false(
            CANVAS_EXPERIMENT_FLAG,
            str(user.distinct_id),
            groups={"organization": str(team.organization_id), "project": str(team.id)},
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team.id)},
            },
            person_properties={"email": user.email},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("canvas_experiment_flag_check_failed", exc_info=True)
        return False
