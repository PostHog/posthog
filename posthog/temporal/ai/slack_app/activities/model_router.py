"""Automatic model choice for a new Slack task.

It runs only for the first message of a thread, because a follow-up joins a sandbox that
already runs and cannot change its runtime.
"""

import json

import structlog
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.llm.managed_decision_model import DEFAULT_DECISION_MODEL
from posthog.llm.system_one import ChoiceAnswer, ChoiceQuestion, JsonValue
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
DECISION_SPAN_NAME = "slack_model_router_decision"


@frozen
class ModelRouterDecision:
    picked: ModelRouterOption
    # What the decision model read: the state and the question.
    request: dict[str, JsonValue]
    answer: ChoiceAnswer


def classify_slack_app_model_router(
    event_text: str,
    options: tuple[ModelRouterOption, ...],
    *,
    team_id: int,
    repository: str | None,
    distinct_id: str | None,
    trace_id: str | None = None,
) -> ModelRouterDecision | None:
    options = options[:GATEWAY_MAX_CHOICE_OPTIONS]
    if len(options) < 2:
        return None
    by_key = {option.model: option for option in options}

    # No TypeSafe fallback: the request is customer text, and TypeSafe is a third party.
    client = build_system_one_client(
        model=MODEL_ROUTER_DECISION_MODEL,
        ai_product="slack_app_routing",
        team_id=team_id,
        distinct_id=distinct_id,
        trace_id=trace_id,
        properties={CLASSIFIER_PROPERTY: "slack_model_router"},
        timeout=MODEL_ROUTER_TIMEOUT_SECONDS,
    )
    state: dict[str, JsonValue] = {"request": event_text, "repository": repository}
    question = ChoiceQuestion(
        instructions=MODEL_ROUTER_INSTRUCTIONS,
        criteria={key: option.description for key, option in by_key.items()},
    )
    result = client.decide(state=state, questions={_QUESTION_ID: question})
    answer = result.answers.get(_QUESTION_ID)
    if not isinstance(answer, ChoiceAnswer) or answer.choice not in by_key:
        logger.warning("slack_app_model_router_unexpected_answer")
        return None
    logger.info("slack_app_model_router_answer", choice=answer.choice, confidence=answer.confidence)
    return ModelRouterDecision(
        picked=by_key[answer.choice], request={"state": state, "question": question.to_json()}, answer=answer
    )


def _capture_decision(
    integration: Integration,
    input: SlackAppModelRouterInput,
    user: User,
    decision: ModelRouterDecision,
    trace_id: str | None,
) -> None:
    # The gateway records no content for a System One call, so the online evaluation reads what
    # the decision model saw and picked from this record. It carries no cost, so spend is not counted twice.
    answer = decision.answer
    capture_slack_event(
        integration,
        "$ai_generation",
        slack_user_id=input.slack_user_id,
        posthog_user=user,
        **{
            "$ai_trace_id": trace_id,
            "$ai_span_name": DECISION_SPAN_NAME,
            "$ai_model": MODEL_ROUTER_DECISION_MODEL,
            "$ai_billable": False,
            "$ai_input": [{"role": "user", "content": json.dumps(decision.request)}],
            "$ai_output_choices": [
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "choice": answer.choice,
                            "confidence": answer.confidence,
                            "probabilities": dict(answer.probabilities),
                        }
                    ),
                }
            ],
            CLASSIFIER_PROPERTY: "slack_model_router",
            "ai_product": "slack_app_routing",
        },
    )


@activity.defn
@close_db_connections
def classify_slack_app_model_router_activity(input: SlackAppModelRouterInput) -> SlackAppModelOverride | None:
    """A model named in the mention always wins, because the author asked for it. The router
    picks only a model: the effort comes from the mention, else from the stored default when
    the router picks that default's model, else the model's own default.
    """
    override = input.model_override
    if (override is not None and override.model) or not input.event_text.strip():
        return override
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

    trace_id = _thread_trace_id(input.slack_team_id, input.thread_ts)
    options: tuple[ModelRouterOption, ...] = ()
    decision: ModelRouterDecision | None = None
    try:
        options = model_router_options(team_id=integration.team_id, user_id=user.id, distinct_id=user.distinct_id)
        decision = classify_slack_app_model_router(
            input.event_text,
            options,
            team_id=integration.team_id,
            repository=input.repository,
            distinct_id=user.distinct_id,
            trace_id=trace_id,
        )
    except Exception:
        logger.exception("slack_app_model_router_failed")
    picked = decision.picked if decision else None

    capture_slack_event(
        integration,
        "slack app model routed",
        slack_user_id=input.slack_user_id,
        posthog_user=user,
        routed=picked is not None,
        model=picked.model if picked else None,
        option_count=len(options),
        has_repository=input.repository is not None,
    )
    if decision is None:
        return override
    _capture_decision(integration, input, user, decision, trace_id)

    return SlackAppModelOverride(
        model=decision.picked.model,
        reasoning_effort=(override.reasoning_effort if override else None) or decision.picked.reasoning_effort,
    )
