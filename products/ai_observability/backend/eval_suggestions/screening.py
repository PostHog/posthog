"""Stage 5: a decision model screens failures the text itself shows, and names what existing evaluations cover.

It ranks candidates and picks example traces. Its rate is never shown, because on real traces it reacts to
surface cues, and it is never asked about hallucination, claimed success or task outcome.
"""

import re
import time
from collections.abc import Mapping, Sequence

from django.conf import settings

from posthog.llm.system_one import (
    Answer,
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    Question,
    SystemOneRequestFailed,
)
from posthog.llm.system_one_client import GATEWAY_MAX_QUESTIONS, SystemOneClient, build_system_one_client
from posthog.models.team import Team
from posthog.temporal.ai_observability.shared_activities import consented_team_ids

from ee.hogai.utils.feature_flags import is_privacy_mode_enabled

from . import catalog
from .coverage import ExistingEval
from .measure import SampledTrace
from .ranking import ScreeningResult

AI_PRODUCT = "aio_eval_suggestions"
# Calibrated on labelled traces: separation was best between 0.8 and 0.9, and 0.5 flagged far too much.
FAILING_PROBABILITY = 0.9
# A dedupe answer below this confidence keeps the candidate and labels it "similar to" the evaluation.
DEDUPE_CONFIDENCE = 0.6
MAX_SCREENED_TRACES = 128
SCREENING_BUDGET_SECONDS = 300
# Dedupe runs before screening and shares the run's time, so it gets a smaller budget of its own.
DEDUPE_BUDGET_SECONDS = 120
MAX_CONSECUTIVE_FAILURES = 3
MAX_STATE_CHARS = 3000
CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_NONE_OPTION = "none"
_DEDUPE_INSTRUCTIONS = (
    "This is the definition of an automated evaluation that checks AI outputs. Which one of these standard checks "
    "does it implement? Pick none when it checks something more specific than any standard check, such as a "
    "product rule or a routing decision."
)
_SENTIMENT_QUESTION = "Does the user sound frustrated, annoyed, or angry with the assistant in this turn?"
_LABELS = {
    "sentiment": "The user sounds frustrated",
    "prompt_injection": "Text tries to override the assistant's instructions",
}


def build_client(team: Team) -> SystemOneClient:
    """Raises SystemOneNotConfigured where no System One server is set up, which a caller treats as a skip.

    Calls carry trace text and evaluation definitions, so an organization in privacy mode keeps them out of the
    gateway's analytics.
    """
    return build_system_one_client(
        model=settings.HOGQL_PROMPT_JEV_MODEL,
        ai_product=AI_PRODUCT,
        team_id=team.pk,
        privacy_mode=is_privacy_mode_enabled(team),
    )


def consented(team: Team) -> bool:
    return team.pk in consented_team_ids([team.pk])


def clean_state(text: str) -> str:
    return CONTROL_CHARACTERS.sub(" ", text)[:MAX_STATE_CHARS]


def _question(template_key: str) -> Question:
    template = catalog.template(template_key)
    if template_key == "sentiment":
        return NoulQuestion(instructions=_SENTIMENT_QUESTION)
    if template.output_type == "categorical":
        options = template.output_config.get("options", [])
        return ChoiceQuestion(
            instructions=template.prompt, criteria={option["key"]: option["label"] for option in options}
        )
    return NoulQuestion(instructions=template.prompt)


def failing_probability(template_key: str, answer: Answer) -> tuple[float, str] | None:
    """How likely the answer marks a failure, with a one-line label. None for a refusal or a malformed answer."""
    if isinstance(answer, NoulAnswer):
        return answer.probability, _LABELS.get(template_key, catalog.template(template_key).name)
    if isinstance(answer, ChoiceAnswer):
        template = catalog.template(template_key)
        passing = set(template.output_config.get("passing_rule", {}).get("categories", []))
        labels = {option["key"]: option["label"] for option in template.output_config.get("options", [])}
        return (
            sum(p for option, p in answer.probabilities.items() if option not in passing),
            labels.get(answer.choice, answer.choice),
        )
    return None


def screen(
    client: SystemOneClient,
    template_keys: Sequence[str],
    traces: Sequence[SampledTrace],
    deadline: float | None = None,
) -> list[ScreeningResult]:
    """Ask every template's question about the visible turn of each trace that has text.

    Each call holds one trace: with several traces in one state, the model reads the others as the same
    conversation and scores repeated requests that are not there.
    """
    readable = [t for t in traces if t.final_text.strip()][:MAX_SCREENED_TRACES]
    questions = {key: _question(key) for key in template_keys}
    flagged: dict[str, list[tuple[float, str, str]]] = {key: [] for key in template_keys}
    # Calls run one after another, so the stage stops at its deadline and keeps what it screened. One failed call
    # loses its trace, and a run of them means the gateway is down.
    stop_at = min(time.monotonic() + SCREENING_BUDGET_SECONDS, float("inf") if deadline is None else deadline)
    screened = failures = 0
    for sampled in readable:
        if time.monotonic() >= stop_at or failures >= MAX_CONSECUTIVE_FAILURES:
            break
        state = {"turn": clean_state(sampled.turn_text)}
        keys = list(questions)
        try:
            for start in range(0, len(keys), GATEWAY_MAX_QUESTIONS):
                batch = keys[start : start + GATEWAY_MAX_QUESTIONS]
                answers = client.decide(state=state, questions={key: questions[key] for key in batch}).answers
                for key in batch:
                    scored = failing_probability(key, answers[key])
                    if scored is not None and scored[0] >= FAILING_PROBABILITY:
                        flagged[key].append((scored[0], sampled.trace.id, scored[1]))
        except SystemOneRequestFailed:
            failures += 1
            continue
        failures = 0
        screened += 1
    if screened == 0 and failures:
        raise SystemOneRequestFailed("Every screening call failed")
    return [
        ScreeningResult(
            template_key=key,
            screened=screened,
            flagged=[(trace_id, label) for _, trace_id, label in sorted(flagged[key], reverse=True)],
        )
        for key in template_keys
    ]


def dedupe(
    client: SystemOneClient, evals: Sequence[ExistingEval], options: Mapping[str, str], deadline: float | None = None
) -> dict[str, list[tuple[ExistingEval, float]]]:
    """For each candidate key, every existing evaluation the model says implements it, most confident first."""
    choices = dict(list(options.items())[:15]) | {_NONE_OPTION: "Something more specific than any standard check"}
    question = ChoiceQuestion(instructions=_DEDUPE_INSTRUCTIONS, criteria=choices)
    matches: dict[str, list[tuple[ExistingEval, float]]] = {}
    stop_at = min(time.monotonic() + DEDUPE_BUDGET_SECONDS, float("inf") if deadline is None else deadline)
    failures = 0
    # One definition per call, for the same reason as screen(). A failed call loses one match, never the screening.
    for existing in evals:
        if time.monotonic() >= stop_at or failures >= MAX_CONSECUTIVE_FAILURES:
            break
        try:
            answer = client.decide(
                state={"definition": clean_state(existing.definition_text)}, questions={"covers": question}
            ).answers["covers"]
        except SystemOneRequestFailed:
            failures += 1
            continue
        failures = 0
        if not isinstance(answer, ChoiceAnswer) or answer.choice == _NONE_OPTION:
            continue
        matches.setdefault(answer.choice, []).append((existing, answer.confidence))
    return {key: sorted(found, key=lambda match: -match[1]) for key, found in matches.items()}
