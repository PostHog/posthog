"""The words on a suggestion card.

A card leads with the problem in the app's own terms and the number that makes it concrete, then says what adding
the evaluation does and what it costs. How the problem was measured goes in `reason`, which the card shows only
on request.
"""

import re
import math
from collections.abc import Sequence

from posthog.dataclasses import frozen

from .adapters import REFUSALS, REPEAT_THRESHOLD, REPEATED_TOOL_CALLS, SENSITIVE_DATA, UNRECOVERED_ERRORS, AdaptedCheck
from .catalog import EvalTemplate
from .coverage import DEAD_LOOKBACK, EvalFix
from .profile import StructuredGap

FREE = "No AI provider cost, and you see results on recent traffic right away."
# Below 1 in 10, "1 in N" reads more easily than a percentage.
ONE_IN_N_BELOW = 0.1
# Below this ratio, "N× more often" overstates the difference, so the card gives both shares instead.
MIN_RATIO = 2.0
# The top of a priority or severity scale, which a card calls "urgent": P0, sev-1, critical, high.
URGENT_VALUE = re.compile(
    r"^(?:(?:p|sev|s)[-_ ]?)?[01]$|^(?:critical|blocker|urgent|highest|high|severe|major|must[-_ ]fix)$",
    re.IGNORECASE,
)
UNITS = {"session": "conversations", "trace": "traces", "generation": "generations"}


@frozen
class CardText:
    headline: str
    outcome: str
    reason: str


@frozen
class _CheckWords:
    # What the rate counts: "1 in 125 traces", "12% of answers".
    noun: str
    # The failure after "1 in N {noun}", then after "N% of {noun}".
    singular: str
    plural: str
    # `{scope}` takes the segment the check runs on, such as "batch ", or nothing.
    checks: str
    reason: str


CHECKS: dict[str, _CheckWords] = {
    UNRECOVERED_ERRORS: _CheckWords(
        noun="traces",
        singular="ends on a failed call",
        plural="end on a failed call",
        checks="Checks every {scope}trace for a tool or model call that failed with no recovery.",
        reason="A tool or model call failed and no later attempt succeeded. Approval pauses and cancellations don't count.",
    ),
    REPEATED_TOOL_CALLS: _CheckWords(
        noun="traces",
        singular=f"repeats an identical tool call {REPEAT_THRESHOLD} or more times",
        plural=f"repeat an identical tool call {REPEAT_THRESHOLD} or more times",
        checks="Checks every {scope}trace for an agent stuck calling one tool with the same arguments.",
        reason=(
            f"The agent called one tool with the same arguments {REPEAT_THRESHOLD} or more times in a trace. "
            "Dispatcher and polling tools are skipped."
        ),
    ),
    REFUSALS: _CheckWords(
        noun="answers",
        singular="is a refusal",
        plural="are refusals",
        checks="Checks the final answer of every {scope}trace for a refusal.",
        reason="The final answer refuses the request. Refusals in earlier steps or in tool output don't count.",
    ),
    SENSITIVE_DATA: _CheckWords(
        noun="answers",
        singular="includes an email address, card number or secret key",
        plural="include an email address, card number or secret key",
        checks="Checks the final answer of every {scope}trace for email addresses, card numbers and secret keys.",
        reason=(
            "The final answer contains an email address, a card number, or a secret key. "
            "Links and version numbers don't count."
        ),
    ),
}


@frozen
class _JudgeWords:
    headline: str
    # `{units}` takes what the judge runs on: conversations, traces or generations.
    checks: str


JUDGES: dict[str, _JudgeWords] = {
    "user_correction": _JudgeWords(
        headline="Some users have to correct the assistant",
        checks="Flags {units} where the user corrects the assistant or repeats a request.",
    ),
    "sentiment": _JudgeWords(
        headline="Some users sound frustrated",
        checks="Labels how the user feels in the last user message of each generation, so you can find the frustrated ones.",
    ),
    "prompt_injection": _JudgeWords(
        headline="Some messages try to override the assistant's instructions",
        checks="Flags injection and jailbreak attempts in user messages and in content the model reads.",
    ),
}


def _plain(value: str) -> str:
    return value.replace("_", " ")


def _sentence_start(text: str) -> str:
    return text[:1].upper() + text[1:]


def _either(values: Sequence[str]) -> str:
    quoted = [f'"{value}"' for value in values]
    return quoted[0] if len(quoted) == 1 else f"{', '.join(quoted[:-1])} or {quoted[-1]}"


def cost_clause(weekly_cost_usd: float | None, *, free: bool) -> str:
    if free:
        return FREE
    if weekly_cost_usd is None:
        return "Your AI provider key pays for each run."
    if weekly_cost_usd < 0.01:
        return "Under $0.01 a week on your AI provider key."
    return f"About ${weekly_cost_usd:,.2f} a week on your AI provider key."


def code_check_text(check: AdaptedCheck, failure_rate: float, segment: str | None) -> CardText:
    """`segment` is the value the check's filter keeps, such as "batch", or None when it runs on all traffic."""
    words = CHECKS.get(check.key) or _CheckWords(
        noun="traces",
        singular=f'fails the "{check.name}" check',
        plural=f'fail the "{check.name}" check',
        checks=f'Runs the "{check.name}" check on every {{scope}}trace.',
        reason=check.description,
    )
    scope = f"{_plain(segment)} " if segment else ""
    noun = f"{scope}{words.noun}"
    headline = (
        f"1 in {round(1 / failure_rate):,} {noun} {words.singular}"
        if failure_rate < ONE_IN_N_BELOW
        else f"{failure_rate:.0%} of {noun} {words.plural}"
    )
    return CardText(headline=headline, outcome=f"{words.checks.replace('{scope}', scope)} {FREE}", reason=words.reason)


@frozen
class EvalText:
    name: str
    description: str


@frozen
class _GapWords:
    # How the card says the items carry the values: `labeled "bug"`, `marked urgent`.
    marked: str
    # What the judge checks, without a closing full stop.
    checks: str


def is_urgent(gap: StructuredGap) -> bool:
    """Whether every over-used value is the top of an urgency scale, which the card calls "urgent"."""
    return gap.meaning == "urgency" and all(URGENT_VALUE.match(value) for value in gap.values)


def _gap_words(gap: StructuredGap) -> _GapWords:
    items = f"{_plain(gap.segment_value)} {gap.items}"
    values = _either(gap.values)
    if gap.meaning == "label":
        return _GapWords(
            marked=f"labeled {values}", checks=f"Checks whether {items} labeled {values} are labeled correctly"
        )
    if is_urgent(gap):
        return _GapWords(marked="marked urgent", checks=f"Checks whether {items} marked urgent deserve it")
    return _GapWords(marked=f"marked {values}", checks=f"Checks whether {items} marked {values} are marked correctly")


def gap_eval_text(gap: StructuredGap) -> EvalText:
    """The name and description of the judge a gap card drafts, in the card's own words."""
    words = _gap_words(gap)
    return EvalText(
        name=_sentence_start(f"{_plain(gap.segment_value)} {gap.items} {words.marked}"), description=words.checks
    )


def gap_text(gap: StructuredGap, cost: str) -> CardText:
    items = f"{_plain(gap.segment_value)} {gap.items}"
    words = _gap_words(gap)
    marked, checks = words.marked, f"{words.checks}."
    ratio = gap.segment_rate / gap.other_rate if gap.other_rate else math.inf
    headline = (
        f"{_sentence_start(items)} are {marked} {round(ratio)}× more often"
        if math.isfinite(ratio) and ratio >= MIN_RATIO
        else f"{gap.segment_rate:.0%} of {items} are {marked}, compared with {gap.other_rate:.0%} elsewhere"
    )
    reason = (
        f"Traces with {gap.segment_key} = {gap.segment_value} mark {gap.segment_rate:.0%} of their {gap.items} "
        f"{' or '.join(gap.values)}, while other {gap.segment_key} values mark {gap.other_rate:.1%}."
    )
    return CardText(headline=headline, outcome=f"{checks} {cost}", reason=reason)


def judge_text(template: EvalTemplate, target: str, cost: str) -> CardText:
    units = UNITS.get(target, "traces")
    words = JUDGES.get(template.key) or _JudgeWords(headline=template.name, checks=f"{template.description}.")
    return CardText(
        headline=words.headline,
        outcome=f"{words.checks.replace('{units}', units)} {cost}",
        reason=(
            f"Possible issue: a model flagged the examples in a sample of recent {units}. "
            "How often it happens is not measured yet."
        ),
    )


def fix_text(fix: EvalFix) -> CardText:
    name = fix.evaluation_name
    lookback = f"{DEAD_LOOKBACK.days} days"
    if fix.problem == "one_outcome":
        return CardText(
            headline=f'Your "{name}" eval gives the same answer almost every time',
            outcome=(
                "Check that its prompt can tell a pass from a fail."
                if fix.evaluation_type == "llm_judge"
                else "Check that its code can return both answers."
            ),
            reason=(
                f"It returned {fix.dominant_outcome} on {fix.dominant_share:.0%} of {fix.graded_runs:,} graded runs "
                f"in {lookback}, and gives the same reasoning for both answers."
            ),
        )
    headline = f'Your "{name}" eval stopped running'
    if not fix.has_conditions:
        return CardText(
            headline=headline,
            outcome="It has no trigger conditions, so it runs on nothing. Add a condition to choose what it checks.",
            reason=f"It is enabled but has no condition sets, and it has no runs in {lookback}.",
        )
    window = f"{fix.window_days} days" if fix.window_days != 1 else "day"
    change = fix.filter_change
    if change:
        return CardText(
            headline=headline,
            outcome=(
                f"Its filter looks for {change.key} = {change.old_value}, which your traffic stopped sending. "
                f"The fix changes it to {change.key} = {change.new_value}, so the eval runs again."
            ),
            reason=(
                f"It has no runs in {lookback}. No AI event from the last {window} has "
                f"{change.key} = {change.old_value}, and the closest value sent is {change.new_value}."
            ),
        )
    return CardText(
        headline=headline,
        outcome=f"Its filters match none of your AI events from the last {window}, so it checks nothing until they change.",
        reason=f"It has no runs in {lookback}.",
    )
