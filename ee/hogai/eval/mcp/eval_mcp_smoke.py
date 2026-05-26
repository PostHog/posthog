"""Smoke eval for the MCP server.

A single end-to-end case that proves: wrangler boots, the MCP client connects,
Claude is able to discover tools and call at least one of them, and a final
answer is returned. Scoring is intentionally loose — we just want to detect
total breakage.
"""

from __future__ import annotations

from braintrust import EvalCase

from ..base import BaseMaxEval
from ..scorers.mcp import LatencyMs, ToolCallCount
from .mcp_runner import RunResult, run_prompt


async def eval_mcp_smoke(mcp_server, pytestconfig):
    async def task(prompt: str) -> RunResult:
        return await run_prompt(mcp_server, prompt)

    await BaseMaxEval(
        experiment_name="mcp-smoke",
        task=task,
        scores=[
            ToolCallCount(min_count=1, max_count=8),
            LatencyMs(),
        ],
        data=[
            EvalCase(
                input="What insights were created by me in the last 3 months? Just give me the count and a couple of names.",
                expected=None,
            ),
        ],
        pytestconfig=pytestconfig,
        is_public=False,
        no_send_logs=True,
    )
