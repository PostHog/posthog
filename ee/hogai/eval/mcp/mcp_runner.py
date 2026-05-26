"""LLM ↔ MCP tool-use loop used by the eval harness.

Connects an Anthropic Claude model to the local MCP server via the official
``mcp`` Python SDK over Streamable HTTP, runs a tool-use loop, and returns a
record of every tool call (name, arguments, latency) plus the final answer.
"""

from __future__ import annotations

import os
import time
import asyncio
from dataclasses import dataclass, field
from typing import Any

import anthropic
from anthropic.types import MessageParam, ToolParam, ToolResultBlockParam, ToolUseBlock
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .harness import MCPServer

DEFAULT_MODEL = os.environ.get("POSTHOG_MCP_EVAL_MODEL", "claude-sonnet-4-5")
DEFAULT_MAX_TOOL_ITERATIONS = 10
DEFAULT_MAX_TOKENS = 4096


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    latency_ms: float
    is_error: bool
    result_text: str


@dataclass
class RunResult:
    final_answer: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    total_latency_ms: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    stop_reason: str | None = None
    iterations: int = 0


def _mcp_tools_to_anthropic(mcp_tools: list[Any]) -> list[ToolParam]:
    out: list[ToolParam] = []
    for tool in mcp_tools:
        schema = tool.inputSchema or {"type": "object", "properties": {}}
        out.append(
            ToolParam(
                name=tool.name,
                description=tool.description or "",
                input_schema=schema,
            )
        )
    return out


def _extract_text(content_blocks: list[Any]) -> str:
    parts: list[str] = []
    for block in content_blocks:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    return "\n".join(parts)


async def _run_loop(
    session: ClientSession,
    *,
    client: anthropic.AsyncAnthropic,
    prompt: str,
    model: str,
    max_iterations: int,
    max_tokens: int,
) -> RunResult:
    tools_resp = await session.list_tools()
    anthropic_tools = _mcp_tools_to_anthropic(tools_resp.tools)

    messages: list[MessageParam] = [{"role": "user", "content": prompt}]
    result = RunResult(final_answer="")
    overall_start = time.monotonic()

    for iteration in range(max_iterations):
        result.iterations = iteration + 1
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            tools=anthropic_tools,
            messages=messages,
        )
        if response.usage is not None:
            result.total_input_tokens += response.usage.input_tokens
            result.total_output_tokens += response.usage.output_tokens
        result.stop_reason = response.stop_reason

        if response.stop_reason != "tool_use":
            result.final_answer = _extract_text(response.content)
            break

        tool_use_blocks = [b for b in response.content if isinstance(b, ToolUseBlock)]
        messages.append({"role": "assistant", "content": response.content})

        tool_results: list[ToolResultBlockParam] = []
        for block in tool_use_blocks:
            args = block.input if isinstance(block.input, dict) else {}
            call_start = time.monotonic()
            is_error = False
            try:
                tool_response = await session.call_tool(block.name, args)
                result_text = _extract_text(tool_response.content)
                is_error = bool(getattr(tool_response, "isError", False))
            except Exception as exc:  # noqa: BLE001
                result_text = f"Tool call failed: {exc!r}"
                is_error = True
            latency_ms = (time.monotonic() - call_start) * 1000
            result.tool_calls.append(
                ToolCallRecord(
                    name=block.name,
                    arguments=args,
                    latency_ms=latency_ms,
                    is_error=is_error,
                    result_text=result_text,
                )
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                    "is_error": is_error,
                }
            )

        messages.append({"role": "user", "content": tool_results})
    else:
        result.final_answer = "[harness] hit max tool-use iterations without a final answer"

    result.total_latency_ms = (time.monotonic() - overall_start) * 1000
    return result


async def run_prompt(
    server: MCPServer,
    prompt: str,
    *,
    client: anthropic.AsyncAnthropic | None = None,
    model: str = DEFAULT_MODEL,
    max_iterations: int = DEFAULT_MAX_TOOL_ITERATIONS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> RunResult:
    """Connect to the MCP server, run the prompt through Claude, return a RunResult.

    Pass ``client`` to share a connection pool across cases; otherwise a
    one-shot ``AsyncAnthropic`` is created and closed for this call.
    """

    headers = {
        "Authorization": server.auth_header,
        "Accept": "application/json, text/event-stream",
    }
    owns_client = client is None
    anthropic_client = client or anthropic.AsyncAnthropic()
    try:
        async with streamablehttp_client(server.url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await _run_loop(
                    session,
                    client=anthropic_client,
                    prompt=prompt,
                    model=model,
                    max_iterations=max_iterations,
                    max_tokens=max_tokens,
                )
    finally:
        if owns_client:
            await anthropic_client.close()


def run_prompt_sync(server: MCPServer, prompt: str, **kwargs: Any) -> RunResult:
    return asyncio.run(run_prompt(server, prompt, **kwargs))
