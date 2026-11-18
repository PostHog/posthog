"""The words on a suggestion card.

A card to add an evaluation has a stable title for the issue it checks, a one-sentence summary of what it flags and
where, and an observation from the sample that made the run suggest it. The rule it applies goes in the draft's
description and why it matters in `reason`, which the card shows under Details. The card formats cost and sampling
from their own fields.

A card about an existing evaluation names the condition the run observed and a next step. It never claims more than
the run measured: no matching events is not an execution failure.
"""

import re
from collections.abc import Sequence
from datetime import timedelta

from posthog.dataclasses import frozen

from .adapters import REFUSALS, REPEAT_THRESHOLD, REPEATED_TOOL_CALLS, UNRECOVERED_ERRORS, AdaptedCheck
from .call_review import ReviewCard
from .catalog import EvalTemplate
from .config import REVIEW_WINDOW, WINDOW
from .coverage import DEAD_LOOKBACK, EvalFix
from .profile import StructuredGap

# The top of a priority or severity scale, which a card calls "urgent": P0, sev-1, critical, high.
URGENT_VALUE = re.compile(
    r"^(?:(?:p|sev|s)[-_ ]?)?[01]$|^(?:critical|blocker|urgent|highest|high|severe|major|must[-_ ]fix)$",
    re.IGNORECASE,
)
UNITS = {"session": "conversations", "trace": "traces", "generation": "generations"}
UNIT = {"session": "conversation", "trace": "trace", "generation": "generation"}


@frozen
class CardText:
    headline: str
    outcome: str
    reason: str
    # What the sample showed, such as "9 of 27 sampled generations flagged", and where it came from.
    observation: str = ""
    observation_scope: str = ""


def _plain(value: str) -> str:
    return value.replace("_", " ")


def _sentence_start(text: str) -> str:
    return text[:1].upper() + text[1:]


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text.endswith((".", "!", "?")) else f"{text}."


def _either(values: Sequence[str]) -> str:
    quoted = [f'"{value}"' for value in values]
    return quoted[0] if len(quoted) == 1 else f"{', '.join(quoted[:-1])} or {quoted[-1]}"


def _days(window: timedelta) -> str:
    return "day" if window.days == 1 else f"{window.days} days"


def sampled_from(window: timedelta) -> str:
    return f"Sampled from the last {_days(window)}"


def _units(target: str, count: int) -> str:
    return UNIT.get(target, "trace") if count == 1 else UNITS.get(target, "traces")


def flagged(failed: int, of: int, target: str, verb: str = "flagged") -> str:
    """ "9 of 27 sampled generations flagged", with both counts from the same sample."""
    return f"{failed:,} of {of:,} sampled {_units(target, of)} {verb}"


@frozen
class _CheckWords:
    summary: str
    rule: str
    why: str


CHECKS: dict[str, _CheckWords] = {
    UNRECOVERED_ERRORS: _CheckWords(
        summary="Flags traces where a tool or model call fails and no later attempt succeeds.",
        rule=(
            "Fails when the last call to a tool, or the last model call, ends in an error. Each tool counts by its "
            "span name. Approval pauses and cancellations aren't errors."
        ),
        why="The agent carries on without that call's result.",
    ),
    REPEATED_TOOL_CALLS: _CheckWords(
        summary=f"Flags traces where the agent calls one tool with the same arguments {REPEAT_THRESHOLD} or more times.",
        rule=(
            f"Fails when the agent calls one tool with the same arguments {REPEAT_THRESHOLD} or more times. "
            "Dispatcher and polling tools repeat by design, so they're skipped."
        ),
        why="Each repeat adds time and cost.",
    ),
    REFUSALS: _CheckWords(
        summary="Flags traces where the final answer refuses what the user asked.",
        rule="Fails when the final answer refuses the request. Refusals in earlier steps or in tool output don't count.",
        why="The user doesn't get what they asked for.",
    ),
}


def check_words(check: AdaptedCheck) -> _CheckWords:
    return CHECKS.get(check.key) or _CheckWords(
        summary=f'Flags traces that fail the "{check.name}" check.',
        rule=_sentence(check.description),
        why="",
    )


def code_check_text(check: AdaptedCheck, failed: int, of: int, segment: str | None) -> CardText:
    """`segment` is the value the check's filter keeps, such as "batch", or None when it runs on all traffic."""
    words = check_words(check)
    summary = words.summary
    if segment:
        summary = summary.replace("Flags traces", f"Flags {_plain(segment)} traces", 1)
    return CardText(
        headline=check.name,
        outcome=summary,
        reason=words.why,
        observation=flagged(failed, of, "trace"),
        observation_scope=sampled_from(WINDOW),
    )


@frozen
class _JudgeWords:
    title: str
    # `{units}` takes what the judge runs on: conversations, traces or generations.
    summary: str


JUDGES: dict[str, _JudgeWords] = {
    "user_correction": _JudgeWords(
        title="Users correcting the assistant",
        summary="Flags {units} where the user corrects the assistant or repeats a request.",
    ),
    "sentiment": _JudgeWords(
        title="Frustrated users",
        summary="Labels the sentiment of the last user message in each generation, so you can find frustrated users.",
    ),
}


def judge_text(template: EvalTemplate, target: str, flagged_count: int, screened: int) -> CardText:
    """A catalog judge that a screening model flagged in `flagged_count` of `screened` sampled traces. Screening
    reads one item per trace whatever the judge's target, so the observation counts traces."""
    words = JUDGES.get(template.key) or _JudgeWords(title=template.name, summary=_sentence(template.description))
    return CardText(
        headline=words.title,
        outcome=words.summary.replace("{units}", UNITS.get(target, "traces")),
        reason="",
        observation=flagged(flagged_count, screened, "trace", "flagged by a screening model"),
        observation_scope=sampled_from(WINDOW),
    )


@frozen
class EvalText:
    name: str
    description: str


@frozen
class _GapWords:
    # How the card says the items carry the values: `labeled "bug"`, `marked urgent`.
    marked: str
    # The rule the judge applies, as a sentence.
    rule: str


def is_urgent(gap: StructuredGap) -> bool:
    """Whether every over-used value is the top of an urgency scale, which the card calls "urgent"."""
    return gap.meaning == "urgency" and all(URGENT_VALUE.match(value) for value in gap.values)


def _gap_words(gap: StructuredGap) -> _GapWords:
    items = f"{_plain(gap.segment_value)} {gap.items}"
    values = _either(gap.values)
    if gap.meaning == "label":
        return _GapWords(
            marked=f"labeled {values}",
            rule=f"Fails when a trace has {items} labeled {values} that fit another label better.",
        )
    if is_urgent(gap):
        return _GapWords(
            marked="marked urgent",
            rule=f"Fails when a trace has {items} marked urgent that describe a minor or speculative problem.",
        )
    return _GapWords(
        marked=f"marked {values}",
        rule=f"Fails when a trace has {items} marked {values} that are in a different state.",
    )


def gap_eval_text(gap: StructuredGap) -> EvalText:
    """The name and description of the judge a gap card drafts."""
    words = _gap_words(gap)
    return EvalText(
        name=_sentence_start(f"{_plain(gap.segment_value)} {gap.items} {words.marked}"), description=words.rule
    )


def gap_text(gap: StructuredGap) -> CardText:
    items = f"{_plain(gap.segment_value)} {gap.items}"
    words = _gap_words(gap)
    return CardText(
        headline=gap_eval_text(gap).name,
        outcome=f"Flags {_plain(gap.segment_value)} traces whose {gap.items} {words.marked} don't fit that value.",
        reason="",
        observation=(
            f"{gap.segment_rate:.0%} of sampled {items} are {words.marked}, compared with "
            f"{gap.other_rate:.0%} of {gap.items} elsewhere"
        ),
        observation_scope=sampled_from(WINDOW),
    )


def review_text(card: ReviewCard) -> CardText:
    """The review's own words, with its counts over the calls it read."""
    return CardText(
        headline=card.title,
        outcome=_sentence(card.summary),
        reason=_sentence(card.why),
        observation=flagged(card.failed, card.of, "generation"),
        observation_scope=sampled_from(REVIEW_WINDOW),
    )


def review_code_text(card: ReviewCard, failed: int, of: int) -> CardText:
    """The review's own words, with the code's counts over the calls the review read."""
    return CardText(
        headline=card.title,
        outcome=_sentence(card.summary),
        reason=_sentence(card.why),
        observation=flagged(failed, of, "generation"),
        observation_scope=sampled_from(REVIEW_WINDOW),
    )


def prompt_fix_text(card: ReviewCard) -> CardText:
    """The review's own words, and why the card asks for a prompt change instead of an evaluation."""
    return CardText(
        headline=card.title,
        outcome=(
            f"{_sentence(card.summary)} Most sampled calls break this rule, so an eval would fail almost every call."
        ),
        reason=_sentence(card.why),
        observation=flagged(card.failed, card.of, "generation", "break this rule"),
        observation_scope=sampled_from(REVIEW_WINDOW),
    )


def fix_text(fix: EvalFix) -> CardText:
    """The condition the run observed on an existing evaluation, and a next step. The card names the evaluation."""
    lookback = f"the last {_days(DEAD_LOOKBACK)}"
    if fix.problem == "one_outcome":
        return CardText(
            headline="This eval gives the same result almost every time",
            outcome=(
                f"It returned {fix.dominant_outcome} on {fix.dominant_share:.0%} of {fix.graded_runs:,} graded runs "
                f"in {lookback}. "
                + (
                    "Check that its prompt can tell a pass from a fail."
                    if fix.evaluation_type == "llm_judge"
                    else "Check that its code can return both results."
                )
            ),
            reason="It also gives the same reasoning for both results.",
        )
    if not fix.has_conditions:
        return CardText(
            headline="This eval has no trigger conditions",
            outcome=(
                f"It's enabled but has no condition sets, and it has no runs in {lookback}. "
                "Add a condition to choose what it checks."
            ),
            reason="",
        )
    window = f"the last {fix.window_days} days" if fix.window_days != 1 else "the last day"
    change = fix.filter_change
    if change:
        return CardText(
            headline="A filter value no longer appears in your events",
            outcome=(
                f"No AI events from {window} have {change.key} = {change.old_value}. The closest value sent is "
                f"{change.new_value}. The fix changes the filter to that value."
            ),
            reason=f"It has no runs in {lookback}.",
        )
    return CardText(
        headline="No recent events match this eval",
        outcome=(
            f"No AI events from {window} match this eval's filters. If you still expect traffic, check its filters."
        ),
        reason=f"It has no runs in {lookback}.",
    )
