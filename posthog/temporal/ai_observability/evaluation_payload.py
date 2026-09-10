"""Payload-size budget shared by the trace and session evaluation fetches.

The event-count caps (`MAX_TRACE_EVAL_EVENTS`, `MAX_SESSION_EVAL_EVENTS`) bound how many rows an
evaluation pulls, which is a poor proxy for what actually costs memory: 2,500 near-limit events and
2,500 one-line events are the same number and wildly different payloads. This module adds the
missing dimension — bytes — measured on the preflight scan both fetches already run, before
anything is aggregated into `groupArray`, shipped to the worker and turned into Python objects.

Order matters. The row count stays the first check because it is free; the byte sum forces
ClickHouse to decompress the payload columns, so it only runs once the count has passed. That keeps
a runaway session id cheap to reject and reserves the expensive question for plausible units.

Sits in its own module because `run_trace_evaluation` and `run_session_evaluation` must not import
each other (see the docstring on `run_session_evaluation`).
"""

from typing import Literal

from posthog.temporal.ai_observability.metrics import increment_payload_budget

# Columns the evaluation fetches materialize. `properties` is included because it travels with
# every event even though the judge transcript never renders most of it — it is real bytes in the
# worker either way, and the Hog `evaluation_events` global exposes it directly.
PAYLOAD_BYTES_EXPR = (
    "sum(length(properties)"
    " + length(ifNull(input, ''))"
    " + length(ifNull(output, ''))"
    " + length(ifNull(output_choices, ''))"
    " + length(ifNull(input_state, ''))"
    " + length(ifNull(output_state, ''))"
    " + length(ifNull(tools, '')))"
)

# Raw payload runs larger than the transcript rendered from it: properties, states and tool
# definitions are all bytes in the worker but mostly never reach the judge. This multiple is a
# judgment call with headroom for that gap, anchored to a number that was already reasoned about
# per target rather than invented alongside it. The trace side is deliberately log-only for now
# (see `should_skip_for_payload`), which is how we find out whether this multiple is wrong before
# it can skip anything.
PAYLOAD_BYTES_PER_JUDGE_CHAR = 8


def payload_budget_bytes(judge_max_chars: int) -> int:
    """Payload ceiling for a target, derived from that target's judge transcript budget."""
    return judge_max_chars * PAYLOAD_BYTES_PER_JUDGE_CHAR


def should_skip_for_payload(
    *,
    target: Literal["trace", "session"],
    payload_bytes: int,
    budget_bytes: int,
) -> bool:
    """Record the outcome and say whether the fetch should skip.

    Session enforces. Trace only records that it *would* have skipped: trace evaluations are
    already shipped and running, so enforcing a brand-new dimension on them would start silently
    skipping units that evaluate fine today. The metric gives us the real distribution first;
    flipping trace to enforcing is a deliberate follow-up, not an accident of this change.
    """
    over_budget = payload_bytes > budget_bytes
    if not over_budget:
        increment_payload_budget("within_budget", target=target)
        return False
    increment_payload_budget("over_budget" if target == "session" else "over_budget_not_enforced", target=target)
    return target == "session"
