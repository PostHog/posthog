import os

import structlog
from temporalio import activity

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.mcp_analytics.summarize_session_intents.types import SummarizeMCPSessionIntentsInput

from products.mcp_analytics.backend.models import MCPSession

logger = structlog.get_logger(__name__)

SYSTEM_PROMPT = (
    "You summarise what an AI agent was trying to accomplish during a single MCP session. "
    "You are given the per-tool-call intents the agent recorded, in chronological order. "
    "Reply with at most two sentences in third person. "
    "Be concrete: name the actual product, metric, person, or workflow involved — not generic phrases "
    "like 'analytics question' or 'enhance user experience'. "
    "If the intents span unrelated tasks, lead with the dominant one. "
    "Do not list individual tools, do not echo the input verbatim, and do not pad with filler."
)

_TOOL_CALL_INTENTS_QUERY = """
SELECT JSONExtractString(properties, '$mcp_intent') AS intent
FROM events
WHERE team_id = %(team_id)s
    AND event = 'mcp_tool_call'
    AND JSONExtractString(properties, '$session_id') = %(session_id)s
    AND JSONExtractString(properties, '$mcp_intent') != ''
ORDER BY timestamp ASC
LIMIT 200
FORMAT JSONEachRow
"""


def _build_user_prompt(intents: list[str]) -> str:
    numbered = "\n".join(f"{i + 1}. {intent}" for i, intent in enumerate(intents))
    return f"Per-tool-call intents (chronological):\n{numbered}\n\nSummarise the agent's overall goal in 2-3 sentences."


def _summarize_intents(intents: list[str]) -> str | None:
    if not os.environ.get("OPENAI_API_KEY"):
        logger.warning("openai_api_key_not_set", count=len(intents))
        return None

    # Local import keeps the activity importable without the optional dep when the
    # key is unset; we only need OpenAI at the point of an actual summarisation.
    from posthoganalytics.ai.openai import OpenAI

    client = OpenAI(max_retries=2)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        max_tokens=120,
        timeout=30,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(intents)},
        ],
    )
    content = response.choices[0].message.content if response.choices else None
    if not content:
        return None
    return content.strip()


@database_sync_to_async
def _take_pending_sessions(batch_size: int) -> list[tuple[int, str]]:
    rows = MCPSession.objects.filter(intent__isnull=True).order_by("-session_end")[:batch_size]
    return [(row.team_id, row.session_id) for row in rows]


@database_sync_to_async
def _save_intent(team_id: int, session_id: str, intent: str) -> None:
    MCPSession.objects.filter(team_id=team_id, session_id=session_id).update(intent=intent)


async def _fetch_tool_call_intents(team_id: int, session_id: str) -> list[str]:
    async with get_client() as client:
        rows = await client.read_query_as_jsonl(
            _TOOL_CALL_INTENTS_QUERY,
            query_parameters={"team_id": team_id, "session_id": session_id},
        )
    return [row["intent"] for row in rows if row.get("intent")]


@activity.defn(name="summarize-mcp-session-intents")
async def summarize_mcp_session_intents(input: SummarizeMCPSessionIntentsInput) -> None:
    log = logger.bind(activity="summarize-mcp-session-intents")
    tag_queries(product=Product.MCP, feature=Feature.QUERY, name="mcp_session_intent_summary")

    pending = await _take_pending_sessions(input.batch_size)
    log.info("Found sessions awaiting intent summary", count=len(pending))

    summarised = 0
    skipped = 0
    for team_id, session_id in pending:
        intents = await _fetch_tool_call_intents(team_id, session_id)
        if not intents:
            # Record an explicit empty marker so we don't keep retrying sessions
            # whose tool calls never carried $mcp_intent.
            await _save_intent(team_id, session_id, "No agent intent was recorded for this session.")
            skipped += 1
            continue

        summary = _summarize_intents(intents)
        if not summary:
            skipped += 1
            continue

        await _save_intent(team_id, session_id, summary)
        summarised += 1

    log.info("MCP session intent summary complete", summarised=summarised, skipped=skipped)
