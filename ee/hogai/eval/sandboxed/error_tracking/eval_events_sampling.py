"""Argument-hygiene eval for ``query-error-tracking-issue-events``.

The events tool defaults ``limit=1`` and exposes ``verbosity`` plus
``searchQuery`` / ``filterGroup`` because pulling many sampled events
or asking for raw payloads is expensive (each row carries the full
exception payload, including stack frames). Agents that crank ``limit``
to 20 by default, default to ``verbosity=raw``, or skip the narrowing
filter when the user clearly described one are the regressions this
suite is meant to catch.

Each case names a seeded issue verbatim; ``IssueIdMatchesTarget``
verifies the call used the right per-case UUID. The LLM-judge
``EventsArgsAlignment`` grades the sampled-event arguments against the
case's expected shape.

To run::

    pytest ee/hogai/eval/sandboxed/error_tracking/eval_events_sampling.py
"""

from __future__ import annotations

from typing import Any

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.error_tracking.scorers import (
    ERROR_TRACKING_WRITE_TOOLS,
    EventsArgsAlignment,
    EventsToolUsed,
    IssueIdMatchesTarget,
)
from ee.hogai.eval.sandboxed.error_tracking.seeders import seed_error_tracking_issues
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero, NoToolCall


def _events_case(
    *,
    name: str,
    prompt: str,
    target_issue_name: str,
    events_args: dict[str, Any],
) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        expected={
            "target_issue": {"name": target_issue_name},
            "events_args": events_args,
        },
        setup=seed_error_tracking_issues,
    )


@pytest.mark.django_db
async def eval_events_sampling(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases = [
        # One example, modest verbosity — the prompt only asks for "an example",
        # so cranking limit > 3 or asking for raw is wasteful. Issue described
        # by searchable event fields (team-invite TypeError) rather than the
        # PSQL-only issue name.
        _events_case(
            name="events_default_limit_low",
            prompt="Get me an example exception event for the team-invite TypeError.",
            target_issue_name="Team invite rejected",
            events_args={"limit": "<=3", "verbosity": "summary_or_stack"},
        ),
        # Explicit "raw" ask — the agent should pick verbosity=raw here.
        _events_case(
            name="events_raw_when_asked",
            prompt=(
                "Pull the raw exception payload for one event of the checkout "
                "TimeoutError — I want the full untruncated data."
            ),
            target_issue_name="Checkout API timeout",
            events_args={"limit": "<=3", "verbosity": "raw"},
        ),
        # URL-narrowing ask — `searchQuery` on this endpoint only matches
        # exception-level fields ($exception_types/values/sources/functions
        # + email), NOT $current_url, so the product-correct way to filter
        # by URL here is `filterGroup` with $current_url. The judge prompt
        # accepts an equivalent searchQuery too, but the canonical
        # expectation is the property filter.
        _events_case(
            name="events_search_filter",
            prompt="Find an event for the PDF preview RenderError where the URL contained `/files/preview`.",
            target_issue_name="File preview render failure",
            events_args={
                "filterGroup": [
                    {
                        "key": "$current_url",
                        "type": "event",
                        "operator": "icontains",
                        "value": "/files/preview",
                    }
                ],
            },
        ),
        # Multi-example ask — limit should be at least 3 but not maxed out.
        _events_case(
            name="events_three_examples",
            prompt="Show me three different exception events for the checkout TimeoutError.",
            target_issue_name="Checkout API timeout",
            events_args={"limit": "between_2_and_5"},
        ),
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-error-tracking-events-sampling-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            NoToolCall(forbidden=ERROR_TRACKING_WRITE_TOOLS, name="no_error_tracking_write"),
            EventsToolUsed(),
            EventsArgsAlignment(),
            IssueIdMatchesTarget(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
