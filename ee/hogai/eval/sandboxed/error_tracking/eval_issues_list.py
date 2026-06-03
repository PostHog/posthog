"""Error-tracking issues-list eval cases for the sandboxed agent.

Targets ``query-error-tracking-issues-list`` (added in
``feat(mcp): add generated error tracking query tools``). Each case asks
a broad "what's broken" / "which errors" style question and grades the
agent on:

* whether it called the new typed list tool at all (vs. hallucinating or
  reaching for a generic SQL workaround), and
* whether the filters it passed line up with what the user actually asked
  for (status, search, url substring, ordering, etc.).

``seed_error_tracking_issues`` (see ``seeders.py``) owns the full setup
per-case: it wipes the stale Hedgebox PSQL rows (whose CH events never
land in the sandboxed-eval environment), creates three deterministic
issues with fresh UUIDs, and writes the matching ``$exception`` events
directly to ClickHouse so the MCP tools resolve them. Cases that name a
specific seeded issue (e.g. "Team invite rejected" for the TypeError
search case) work out of the box, and the returned ``lookup_issues`` map
lets a future ``LookupIssueIdInOutput`` extension verify the agent's
final message references the per-case UUID.

To run::

    pytest ee/hogai/eval/sandboxed/error_tracking/eval_issues_list.py
"""

from __future__ import annotations

from typing import Any

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.error_tracking.scorers import (
    ERROR_TRACKING_WRITE_TOOLS,
    IssuesListInputAlignment,
    IssuesListToolUsed,
)
from ee.hogai.eval.sandboxed.error_tracking.seeders import seed_error_tracking_issues
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero, NoToolCall


def _list_case(
    *,
    name: str,
    prompt: str,
    expected_input: dict[str, Any],
) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        expected={"issues_list_input": expected_input},
        setup=seed_error_tracking_issues,
    )


@pytest.mark.django_db
async def eval_issues_list(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases = [
        _list_case(
            name="issues_list_active_default",
            prompt="Which errors are happening in production right now?",
            expected_input={},
        ),
        _list_case(
            name="issues_list_top_by_users",
            prompt="What's the error affecting the most users this week? Just give me the issue name.",
            expected_input={"orderBy": "users", "dateRange": {"date_from": "-7d"}},
        ),
        _list_case(
            name="issues_list_filter_by_url_substring",
            prompt="Show me errors that happened on the /app/files page in the last week.",
            expected_input={"url": "/app/files", "dateRange": {"date_from": "-7d"}},
        ),
        _list_case(
            name="issues_list_resolved",
            prompt="List the errors we've already resolved.",
            expected_input={"status": "resolved"},
        ),
        _list_case(
            name="issues_list_search_typeerror",
            prompt="Find error issues related to TypeError.",
            expected_input={"searchQuery": "TypeError"},
        ),
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-error-tracking-issues-list-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            NoToolCall(forbidden=ERROR_TRACKING_WRITE_TOOLS, name="no_error_tracking_write"),
            IssuesListToolUsed(),
            IssuesListInputAlignment(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
