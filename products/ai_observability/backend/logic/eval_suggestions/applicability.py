"""Stage 3: which checks fit the app, decided from the free profile rather than from a model.

The share of generations that call tools separated agent features from the rest perfectly in the
research, where a model asked "which check fits?" picked at random.
"""

from collections import Counter
from collections.abc import Sequence

from posthog.dataclasses import frozen

from . import adapters
from .adapters import AdaptedCheck
from .measure import SampledTrace, TraceSample
from .profile import DISPATCHER_SHARE, TeamProfile

MIN_TOOL_CALL_SHARE = 0.1
MIN_TEXT_SHARE = 0.5
MIN_MULTI_TURN_SHARE = 0.2
MIN_SESSION_SHARE = 0.5
# A dispatcher is called again and again in the traces that use it; a tool that is merely called alone is not.
MIN_DISPATCHER_CALLS_PER_TRACE = 3
MIN_DISPATCHER_TRACES = 5

# Judges that a decision model can screen from the visible text of a turn. Hallucination, claimed
# success and task outcome need evidence the text does not show, so they are never screened.
PERSON_FACING_JUDGES = ("user_correction", "sentiment")
INJECTION_JUDGE = "prompt_injection"


@frozen
class ContentProfile:
    traces: int
    text_share: float
    multi_turn_share: float
    spanning_days_share: float
    dispatcher_tools: tuple[str, ...]


def _tool_calls(sampled: SampledTrace) -> Counter[str]:
    calls: Counter[str] = Counter()
    for event in sampled.trace.events:
        if event.event == "$ai_generation":
            calls.update(
                tool.strip() for tool in str(event.properties.get("$ai_tools_called") or "").split(",") if tool.strip()
            )
    return calls


def trace_dispatcher_tools(traces: Sequence[SampledTrace]) -> tuple[str, ...]:
    """Tools that take over DISPATCHER_SHARE of the calls in the traces that use them, several times each.

    Team-wide shares miss a dispatcher when the team runs several AI features with their own tools.
    """
    own_calls: Counter[str] = Counter()
    all_calls: Counter[str] = Counter()
    traces_using: Counter[str] = Counter()
    for sampled in traces:
        calls = _tool_calls(sampled)
        total = sum(calls.values())
        for tool, count in calls.items():
            own_calls[tool] += count
            all_calls[tool] += total
            traces_using[tool] += 1
    return tuple(
        sorted(
            tool
            for tool in own_calls
            if traces_using[tool] >= MIN_DISPATCHER_TRACES
            and own_calls[tool] / all_calls[tool] > DISPATCHER_SHARE
            and own_calls[tool] / traces_using[tool] >= MIN_DISPATCHER_CALLS_PER_TRACE
        )
    )


def content_profile(sample: TraceSample) -> ContentProfile:
    traces = sample.traces
    count = len(traces)

    def share(flags: Sequence[bool]) -> float:
        return sum(flags) / count if count else 0.0

    return ContentProfile(
        traces=count,
        text_share=share([bool(t.final_text.strip()) for t in traces]),
        multi_turn_share=share([t.user_messages >= 2 for t in traces]),
        spanning_days_share=share([t.spans_days for t in traces]),
        dispatcher_tools=trace_dispatcher_tools(traces),
    )


@frozen
class Applicability:
    checks: list[AdaptedCheck]
    screened_judges: list[str]
    # Person-facing judges grade a whole conversation when the team sends session ids.
    judge_target: str


def applicable(profile: TeamProfile, content: ContentProfile) -> Applicability:
    checks = [adapters.unrecovered_errors(profile.error_prefixes)]
    if profile.tool_call_share >= MIN_TOOL_CALL_SHARE:
        dispatchers = set(profile.dispatcher_tools) | set(content.dispatcher_tools)
        checks.append(
            adapters.repeated_tool_calls(adapters.skipped_repeat_tools(profile.tool_counts, sorted(dispatchers)))
        )
    if content.text_share >= MIN_TEXT_SHARE:
        checks += [adapters.refusals(), adapters.sensitive_data()]

    judges: list[str] = []
    if content.text_share >= MIN_TEXT_SHARE:
        if content.multi_turn_share >= MIN_MULTI_TURN_SHARE:
            judges += PERSON_FACING_JUDGES
        judges.append(INJECTION_JUDGE)
    multi_turn_sessions = (
        profile.session_share >= MIN_SESSION_SHARE and content.multi_turn_share >= MIN_MULTI_TURN_SHARE
    )
    return Applicability(
        checks=checks, screened_judges=judges, judge_target="session" if multi_turn_sessions else "trace"
    )
