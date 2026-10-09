"""Answering a top-level Slack channel message that did not tag the app.

Nobody asked PostHog anything, so the bar is high on purpose: a wrong answer interrupts a
conversation in public. Jev, a System One decision model, answers two yes/no questions about
the message, and both must clear a strict threshold. A missed question costs the author one
@PostHog, which they can still type.
"""

import structlog
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.llm.managed_decision_model import DEFAULT_DECISION_MODEL
from posthog.llm.system_one import NoulAnswer, NoulQuestion, SystemOneNotConfigured
from posthog.llm.system_one_client import build_system_one_client
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.user import User
from posthog.temporal.ai.slack_app.activities.classifiers import CLASSIFIER_PROPERTY, _thread_trace_id
from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionWorkflowInputs, coerce_mention_workflow_inputs
from posthog.temporal.common.utils import close_db_connections

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.models import UntaggedFollowupMode
from products.slack_app.backend.services.slack_settings import resolve_user_untagged_mode

logger = structlog.get_logger(__name__)

UNPROMPTED_QUESTION_DECISION_MODEL = DEFAULT_DECISION_MODEL
# On the path to the first reply. A miss only means no answer, so a slow call is not worth waiting for.
UNPROMPTED_QUESTION_TIMEOUT_SECONDS = 5.0
# Both judgments must clear this. Tuned for precision over recall, see
# products/slack_app/evals/eval_unprompted_question.py.
UNPROMPTED_QUESTION_MIN_PROBABILITY = 0.85
UNPROMPTED_QUESTION_MAX_CHARS = 2000

ASKS_QUESTION_ID = "asks_for_information"
ANSWERABLE_QUESTION_ID = "answerable_by_posthog"

ASKS_FOR_INFORMATION_INSTRUCTIONS = (
    "`message` is a new top-level post in a team's Slack channel. Nobody tagged an assistant in it. "
    "Is the author asking for a specific piece of information or a specific analysis that they do not have yet?"
)
ASKS_FOR_INFORMATION_TRUE = (
    "A real question or request for facts, numbers, an explanation, or a lookup. "
    "Examples: how many users signed up last week, why did checkout conversion drop yesterday, "
    "which feature flag controls the new onboarding, are there errors on the billing page since the deploy."
)
ASKS_FOR_INFORMATION_FALSE = (
    "Anything else: an announcement, a status update, a statement or an opinion, a rhetorical question, "
    "a social message, a joke, a greeting, a thank-you, a call to meet or talk, a request for a person to "
    "do something, or a question only one named person can answer."
)

ANSWERABLE_INSTRUCTIONS = (
    "PostHog is a product analytics platform. Its assistant can read the team's PostHog data: events, "
    "insights, trends, funnels, retention, dashboards, session recordings, feature flags, experiments, "
    "surveys, error tracking, logs, LLM traces and data warehouse tables. It can also search the PostHog "
    "documentation and read the team's code repositories. "
    "Could that assistant answer the question in `message` correctly and fully, with only those sources?"
)
ANSWERABLE_TRUE = (
    "The answer is in product usage data, error or log data, feature flag or experiment state, "
    "the team's code, or the PostHog documentation."
)
ANSWERABLE_FALSE = (
    "The answer needs knowledge those sources do not hold: plans, opinions, decisions, people's availability, "
    "private conversations, customer contracts, finance, HR, or systems PostHog cannot read. Also false when "
    "the question is too vague to answer, or when it is not a question."
)


@frozen
class UnpromptedQuestionVerdict:
    asks_for_information: float
    answerable_by_posthog: float

    @property
    def answerable(self) -> bool:
        return min(self.asks_for_information, self.answerable_by_posthog) >= UNPROMPTED_QUESTION_MIN_PROBABILITY


def classify_unprompted_question(
    event_text: str,
    *,
    team_id: int,
    distinct_id: str | None,
    trace_id: str | None = None,
) -> UnpromptedQuestionVerdict | None:
    """Ask the decision model whether PostHog can answer this message. ``None`` means no verdict.

    Raises when no System One server is configured or the call fails, so the caller can tell
    an outage from a refusal.
    """
    text = event_text.strip()
    if not text:
        return None
    # No TypeSafe fallback: the message is customer text, and TypeSafe is a third party.
    client = build_system_one_client(
        model=UNPROMPTED_QUESTION_DECISION_MODEL,
        ai_product="slack_app_routing",
        team_id=team_id,
        distinct_id=distinct_id,
        trace_id=trace_id,
        properties={CLASSIFIER_PROPERTY: "unprompted_question"},
        timeout=UNPROMPTED_QUESTION_TIMEOUT_SECONDS,
    )
    result = client.decide(
        state={"message": text[:UNPROMPTED_QUESTION_MAX_CHARS]},
        questions={
            ASKS_QUESTION_ID: NoulQuestion(
                instructions=ASKS_FOR_INFORMATION_INSTRUCTIONS,
                criteria_true=ASKS_FOR_INFORMATION_TRUE,
                criteria_false=ASKS_FOR_INFORMATION_FALSE,
            ),
            ANSWERABLE_QUESTION_ID: NoulQuestion(
                instructions=ANSWERABLE_INSTRUCTIONS,
                criteria_true=ANSWERABLE_TRUE,
                criteria_false=ANSWERABLE_FALSE,
            ),
        },
    )
    asks = result.answers.get(ASKS_QUESTION_ID)
    answerable = result.answers.get(ANSWERABLE_QUESTION_ID)
    # A refusal on either question is a no.
    if not isinstance(asks, NoulAnswer) or not isinstance(answerable, NoulAnswer):
        logger.info("slack_app_unprompted_question_refused")
        return None
    return UnpromptedQuestionVerdict(
        asks_for_information=asks.probability, answerable_by_posthog=answerable.probability
    )


def _load_integration(inputs: PostHogCodeSlackMentionWorkflowInputs) -> Integration:
    return Integration.objects.select_related("team").get(
        id=inputs.integration_id,
        kind="slack",
        integration_id=inputs.slack_team_id,
    )


@activity.defn
@close_db_connections
def classify_unprompted_question_activity(inputs: PostHogCodeSlackMentionWorkflowInputs) -> bool:
    """Whether PostHog should answer, or offer to answer, a top-level message nobody tagged it in.

    Any failure returns ``False``: staying quiet is the safe default when nobody asked.
    """
    inputs = coerce_mention_workflow_inputs(inputs)
    integration = _load_integration(inputs)
    user = User.objects.filter(id=inputs.user_id).first()
    if user is None:
        return False

    verdict: UnpromptedQuestionVerdict | None = None
    try:
        verdict = classify_unprompted_question(
            inputs.event.get("text") or "",
            team_id=integration.team_id,
            distinct_id=user.distinct_id,
            trace_id=_thread_trace_id(inputs.slack_team_id, inputs.event.get("ts")),
        )
    except SystemOneNotConfigured:
        logger.info("slack_app_unprompted_question_system_one_not_configured")
    except Exception:
        logger.exception("slack_app_unprompted_question_classifier_failed")

    answerable = verdict is not None and verdict.answerable
    # The message text stays out of this event: its author never addressed PostHog.
    capture_slack_event(
        integration,
        "slack app unprompted question classified",
        slack_user_id=inputs.event.get("user"),
        posthog_user=user,
        classified=verdict is not None,
        answerable=answerable,
        asks_for_information=verdict.asks_for_information if verdict else None,
        answerable_by_posthog=verdict.answerable_by_posthog if verdict else None,
        threshold=UNPROMPTED_QUESTION_MIN_PROBABILITY,
    )
    if not answerable:
        return False

    from products.slack_app.backend.api import (
        claim_message_handled,  # noqa: PLC0415 — keeps the webhook module off the worker import path
    )

    # An edit of this message that adds a tag starts its own run. Whichever path claims
    # the message first runs, and the other stops.
    if not claim_message_handled(inputs.slack_team_id, inputs.event, "unprompted_question"):
        logger.info("slack_app_unprompted_question_already_handled", slack_team_id=inputs.slack_team_id)
        return False
    return True


@activity.defn
@close_db_connections
def request_unprompted_answer_confirmation_activity(inputs: PostHogCodeSlackMentionWorkflowInputs) -> bool:
    """Apply the author's untagged-message mode to a question the classifier passed.

    Returns ``True`` when the run must stop here: the private offer now waits for the
    author, or the author turned untagged pickups off while this run was in flight.
    """
    from products.slack_app.backend.api import (
        _post_unprompted_answer_prompt,  # noqa: PLC0415 — keeps the webhook module off the worker import path
    )

    inputs = coerce_mention_workflow_inputs(inputs)
    slack_user_id = inputs.event.get("user")
    mode = resolve_user_untagged_mode(inputs.slack_team_id, slack_user_id)
    if mode == UntaggedFollowupMode.AUTO:
        return False
    if mode == UntaggedFollowupMode.NEVER:
        logger.info("slack_app_unprompted_answers_switched_off_mid_run", slack_team_id=inputs.slack_team_id)
        return True

    integration = _load_integration(inputs)
    prompted = _post_unprompted_answer_prompt(SlackIntegration(integration), integration, inputs.event)
    if not prompted:
        # Still held back: answering without the offer the author's setting asks for would break it.
        logger.warning("slack_app_unprompted_answer_prompt_not_delivered", integration_id=integration.id)
    return True
