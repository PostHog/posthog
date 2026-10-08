"""Automatic model choice for a new Slack task.

It runs only for the first message of a thread, because a follow-up joins a sandbox that
already runs and cannot change its runtime.
"""

import structlog
from temporalio import activity

from posthog.llm.managed_decision_model import DEFAULT_DECISION_MODEL
from posthog.llm.system_one import ChoiceAnswer, ChoiceQuestion
from posthog.llm.system_one_client import GATEWAY_MAX_CHOICE_OPTIONS, build_system_one_client
from posthog.models.integration import Integration
from posthog.models.user import User
from posthog.temporal.ai.slack_app.activities.classifiers import CLASSIFIER_PROPERTY, _thread_trace_id
from posthog.temporal.ai.slack_app.types import SlackAppModelOverride, SlackAppModelRouterInput
from posthog.temporal.common.utils import close_db_connections

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.facade.run_preferences import (
    MODEL_ROUTER_INSTRUCTIONS,
    ModelRouterOption,
    model_router_options,
)
from products.slack_app.backend.feature_flags import is_slack_app_model_router_enabled
from products.slack_app.backend.services.slack_settings import resolve_auto_model_choice

logger = structlog.get_logger(__name__)

MODEL_ROUTER_DECISION_MODEL = DEFAULT_DECISION_MODEL
# The router is on the path to the first reply in the thread, so a slow answer costs more
# than a missed one. A miss leaves the run on the default it already had.
MODEL_ROUTER_TIMEOUT_SECONDS = 5.0

_QUESTION_ID = "model"


def classify_slack_app_model_router(
    event_text: str,
    options: tuple[ModelRouterOption, ...],
    *,
    repository: str | None,
    distinct_id: str | None,
    trace_id: str | None = None,
) -> ModelRouterOption | None:
    """`None` when there is nothing to pick between, or the answer is not one of the options."""
    options = options[:GATEWAY_MAX_CHOICE_OPTIONS]
    if len(options) < 2:
        return None
    by_key = {option.key: option for option in options}

    # No TypeSafe fallback: the request is customer text, and TypeSafe is a third party.
    client = build_system_one_client(
        model=MODEL_ROUTER_DECISION_MODEL,
        ai_product="slack_app_routing",
        distinct_id=distinct_id,
        trace_id=trace_id,
        properties={CLASSIFIER_PROPERTY: "slack_model_router"},
        timeout=MODEL_ROUTER_TIMEOUT_SECONDS,
    )
    result = client.decide(
        state={"request": event_text, "repository": repository},
        questions={
            _QUESTION_ID: ChoiceQuestion(
                instructions=MODEL_ROUTER_INSTRUCTIONS,
                criteria={key: option.description for key, option in by_key.items()},
            )
        },
    )
    answer = result.answers.get(_QUESTION_ID)
    if not isinstance(answer, ChoiceAnswer) or answer.choice not in by_key:
        logger.warning("slack_app_model_router_unexpected_answer")
        return None
    logger.info("slack_app_model_router_answer", choice=answer.choice, confidence=answer.confidence)
    return by_key[answer.choice]


@activity.defn
@close_db_connections
def classify_slack_app_model_router_activity(input: SlackAppModelRouterInput) -> SlackAppModelOverride | None:
    """A model named in the mention always wins, because the author asked for it. An effort
    named alone still applies on top of the model the router picks.
    """
    override = input.model_override
    if (override is not None and override.model) or not input.event_text.strip():
        return override
    # The settings row is a cheap query, so it goes before the flag check, which is a network call.
    if not resolve_auto_model_choice(input.slack_team_id, input.slack_user_id):
        return override

    integration = Integration.objects.select_related("team").get(
        id=input.integration_id,
        kind="slack",
        integration_id=input.slack_team_id,
    )
    user = User.objects.filter(id=input.user_id).first()
    if user is None or not is_slack_app_model_router_enabled(integration, distinct_id=user.distinct_id):
        return override

    options = model_router_options(team_id=integration.team_id, user_id=user.id, distinct_id=user.distinct_id)
    try:
        picked = classify_slack_app_model_router(
            input.event_text,
            options,
            repository=input.repository,
            distinct_id=user.distinct_id,
            trace_id=_thread_trace_id(input.slack_team_id, input.thread_ts),
        )
    except Exception:
        logger.exception("slack_app_model_router_failed")
        picked = None

    capture_slack_event(
        integration,
        "slack app model routed",
        slack_user_id=input.slack_user_id,
        posthog_user=user,
        routed=picked is not None,
        model=picked.model if picked else None,
        reasoning_effort=picked.reasoning_effort if picked else None,
        option_count=len(options),
        has_repository=input.repository is not None,
    )
    if picked is None:
        return override

    return SlackAppModelOverride(
        model=picked.model,
        reasoning_effort=(override.reasoning_effort if override else None) or picked.reasoning_effort,
    )
