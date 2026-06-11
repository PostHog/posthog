"""Drill-down ordering eval cases for the error-tracking sandboxed agent.

Targets the canonical workflow encoded in the new error-tracking MCP
prompts:

    query-error-tracking-issues-list
        ↓ (agent picks the right issueId)
    query-error-tracking-issue          ← cheap details (impact, top frame, latest release)
        ↓ (only when concrete examples / replay context are needed)
    query-error-tracking-issue-events   ← sampled exception events
        ↓ ($session_id surfaces here)
    query-session-recordings-list

Each case names a specific seeded issue verbatim and asks for
something that should drive the agent through one or more drill-down
steps. ``IssueDrilldownOrder`` enforces the call sequence;
``IssueIdMatchesTarget`` verifies the agent passed the *per-case* UUID
of the named issue (not the master team's UUID, not a hallucinated
one). Together those two scorers catch the most common regressions:
agents skipping the cheap detail call, agents asking for raw events
when they didn't need them, and agents drilling into the wrong issue.

To run::

    pytest ee/hogai/eval/sandboxed/error_tracking/eval_issue_drilldown.py
"""

from __future__ import annotations

from typing import Any

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.error_tracking.scorers import (
    ERROR_TRACKING_WRITE_TOOLS,
    IssueDrilldownOrder,
    IssueIdMatchesTarget,
    IssueInputAlignment,
)
from ee.hogai.eval.sandboxed.error_tracking.seeders import seed_error_tracking_issues
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero, NoToolCall


def _drilldown_case(
    *,
    name: str,
    prompt: str,
    target_issue_name: str,
    requires_issue: bool = True,
    requires_events: bool = False,
    requires_recordings: bool = False,
    forbids_events: bool = False,
    forbids_recordings: bool = False,
    issue_input: dict[str, Any] | None = None,
) -> SandboxedEvalCase:
    expected: dict[str, Any] = {
        "target_issue": {"name": target_issue_name},
        "drilldown": {
            "requires_issue": requires_issue,
            "requires_events": requires_events,
            "requires_recordings": requires_recordings,
            "forbids_events": forbids_events,
            "forbids_recordings": forbids_recordings,
        },
    }
    if issue_input is not None:
        expected["issue_input"] = issue_input
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        expected=expected,
        setup=seed_error_tracking_issues,
    )


@pytest.mark.django_db
async def eval_issue_drilldown(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases = [
        # Detail-only — impact numbers + a glance at the issue. Should not
        # trigger the heavier events tool or fan out to session recordings.
        # Phrased as a discoverable symptom (TimeoutError on the checkout
        # flow) rather than the PSQL-only issue name; searchQuery on the
        # list tool matches event $exception_types / $exception_values, not
        # ErrorTrackingIssue.name.
        _drilldown_case(
            name="drilldown_checkout_timeout_impact",
            prompt="Tell me the impact (users / sessions / occurrences) of the checkout TimeoutError in the last 14 days.",
            target_issue_name="Checkout API timeout",
            forbids_events=True,
            forbids_recordings=True,
            issue_input={"dateRange": {"date_from": "-14d"}},
        ),
        # Stack-trace ask — requires query-error-tracking-issue-events to pull
        # the sampled exception payload. No replay context asked for, so
        # fanning into session recordings would be wasteful.
        _drilldown_case(
            name="drilldown_pdf_preview_show_examples",
            prompt="Show me an example exception event with stack trace for the PDF preview RenderError.",
            target_issue_name="File preview render failure",
            requires_issue=False,
            requires_events=True,
            forbids_recordings=True,
        ),
        # Pre-error behavior — events first (to extract $session_id), then a
        # session-recordings lookup. The drill-down ordering check insists on
        # all three.
        _drilldown_case(
            name="drilldown_typeerror_session_replay",
            prompt=(
                "Find a session recording where a user hit the team-invite "
                'TypeError ("Cannot read properties of undefined (reading '
                "'email')\") so I can see what they were doing right before "
                "it happened."
            ),
            target_issue_name="Team invite rejected",
            requires_issue=False,
            requires_events=True,
            requires_recordings=True,
        ),
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-error-tracking-issue-drilldown-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            NoToolCall(forbidden=ERROR_TRACKING_WRITE_TOOLS, name="no_error_tracking_write"),
            IssueDrilldownOrder(),
            IssueIdMatchesTarget(),
            IssueInputAlignment(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
