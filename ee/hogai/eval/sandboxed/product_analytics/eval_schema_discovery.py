"""Schema-discovery eval cases for the sandboxed product-analytics agent.

This eval codifies a behavior policy: even for well-known system events
like ``$pageview``, the agent must (1) load the ``query-trends`` MCP tool
schema via Claude Code's ``ToolSearch`` (the sandbox's equivalent of the
MCP CLI's ``info <tool>`` command), (2) call ``read-data-schema`` to
verify the event exists in the team's data, and (3) only then invoke
``query-trends`` to build the insight.

Correctness of the produced trends query itself is not scored here — that
is ``ee/hogai/eval/ci/eval_trends.py``'s job. This eval grades ordering
and discovery hygiene.

To run:
    pytest ee/hogai/eval/sandboxed/product_analytics/eval_schema_discovery.py
"""

from __future__ import annotations

from typing import Any

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.product_analytics.scorers import INSIGHT_WRITE_TOOLS, SchemaDiscoveryOrder
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero, NoToolCall


def _discovery_case(
    *,
    name: str,
    prompt: str,
    query_tool: str,
    data_kind: str,
    data_search_any_of: list[str],
) -> SandboxedEvalCase:
    expected: dict[str, Any] = {
        "schema_discovery": {
            "query_tool": query_tool,
            "data_kind": data_kind,
            "data_search_any_of": data_search_any_of,
        },
    }
    return SandboxedEvalCase(name=name, prompt=prompt, expected=expected)


@pytest.mark.django_db
async def eval_schema_discovery(sandboxed_demo_data, pytestconfig, posthog_client):
    cases = [
        _discovery_case(
            name="schema_discovery_pageview_7d",
            prompt="query pageviews for the last 7 days",
            query_tool="query-trends",
            data_kind="events",
            data_search_any_of=["pageview", "$pageview"],
        ),
        # System event that *is* ingested in Hedgebox demo data — tests
        # schema-first behavior for a canonical-looking event where the
        # agent is also expected to successfully run the trend after
        # discovery.
        _discovery_case(
            name="schema_discovery_rageclick_weekly",
            prompt="show me the daily trend of $rageclick events for the last week",
            query_tool="query-trends",
            data_kind="events",
            data_search_any_of=["rageclick", "$rageclick"],
        ),
        _discovery_case(
            name="schema_discovery_identify_30d",
            prompt="show a trend of $identify events over the last 30 days",
            query_tool="query-trends",
            data_kind="events",
            data_search_any_of=["identify", "$identify"],
        ),
        # Custom (non-system) event — agent *must* verify this exists before
        # querying, so this is the case where we'd expect schema discovery to
        # already happen today. Hedgebox demo data fires ``downloaded_file``.
        _discovery_case(
            name="schema_discovery_file_downloads_7d",
            prompt="show me the file downloads trend for the last 7 days",
            query_tool="query-trends",
            data_kind="events",
            data_search_any_of=["download", "downloaded_file"],
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-schema-discovery",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            NoToolCall(forbidden=INSIGHT_WRITE_TOOLS, name="no_persistent_insight_save"),
            SchemaDiscoveryOrder(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
