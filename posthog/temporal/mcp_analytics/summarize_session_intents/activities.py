import os
import asyncio
from datetime import timedelta

from django.db import connection
from django.utils import timezone

import structlog
from temporalio import activity

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.mcp_analytics.summarize_session_intents.types import SummarizeMCPSessionIntentsInput

from products.mcp_analytics.backend.models import MCPSession

logger = structlog.get_logger(__name__)

# PostHog's own team — summarised ahead of everyone else so internal dogfooding
# is never starved by external traffic.
_PRIORITY_TEAM_ID = 2

# Per-team cap for non-priority teams in a single batch. Stops one team from
# monopolising the global LLM budget by emitting many unique session ids.
_PER_TEAM_CAP = 10

# Placeholder written when an MCP session has no recordable tool-call intents.
# Exported so downstream consumers (e.g. intent clustering) can filter it out
# of their corpus — clustering an "empty" placeholder produces a meaningless
# pseudo-cluster in real data.
NO_INTENT_RECORDED_FALLBACK = "No agent intent was recorded for this session."

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
    AND JSONExtractString(properties, '$mcp_session_id') = %(session_id)s
    AND JSONExtractString(properties, '$mcp_intent') != ''
ORDER BY timestamp ASC
LIMIT 200
FORMAT JSONEachRow
"""


def _build_user_prompt(intents: list[str]) -> str:
    numbered = "\n".join(f"{i + 1}. {intent}" for i, intent in enumerate(intents))
    return f"Per-tool-call intents (chronological):\n{numbered}\n\nSummarise the agent's overall goal in 2-3 sentences."


def _summarize_intents_sync(intents: list[str]) -> str | None:
    """Blocking OpenAI call; callers wrap in asyncio.to_thread for concurrency."""
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


_PENDING_SESSIONS_SQL = """
WITH ranked AS (
    SELECT
        team_id,
        session_id,
        session_end,
        ROW_NUMBER() OVER (PARTITION BY team_id ORDER BY session_end DESC) AS rn,
        (team_id = %(priority_team_id)s) AS is_priority
    FROM posthog_mcp_session
    WHERE intent IS NULL AND session_end < %(cutoff)s
)
SELECT team_id, session_id
FROM ranked
WHERE is_priority OR rn <= %(per_team_cap)s
ORDER BY is_priority DESC, session_end DESC
LIMIT %(batch_size)s
"""


@database_sync_to_async
def _take_pending_sessions(batch_size: int, idle_minutes: int) -> list[tuple[int, str]]:
    """Pick sessions that are eligible for summarisation.

    Eligible = intent is unset AND last event landed more than idle_minutes ago,
    so we don't summarise sessions that may still be receiving tool calls.
    Priority team rows come first; other teams are capped per batch so one noisy
    team can't monopolise the LLM budget.
    """
    cutoff = timezone.now() - timedelta(minutes=idle_minutes)
    with connection.cursor() as cursor:
        cursor.execute(
            _PENDING_SESSIONS_SQL,
            {
                "priority_team_id": _PRIORITY_TEAM_ID,
                "cutoff": cutoff,
                "per_team_cap": _PER_TEAM_CAP,
                "batch_size": batch_size,
            },
        )
        return [(int(team_id), session_id) for team_id, session_id in cursor.fetchall()]


@database_sync_to_async
def _save_intent(team_id: int, session_id: str, intent: str) -> None:
    # Cross-team activity — picks pending rows across all teams in one pass.
    MCPSession.objects.unscoped().filter(team_id=team_id, session_id=session_id).update(intent=intent)


async def _fetch_tool_call_intents(team_id: int, session_id: str) -> list[str]:
    async with get_client() as client:
        rows = await client.read_query_as_jsonl(
            _TOOL_CALL_INTENTS_QUERY,
            query_parameters={"team_id": team_id, "session_id": session_id},
        )
    return [row["intent"] for row in rows if row.get("intent")]


async def _summarise_one(
    team_id: int,
    session_id: str,
    semaphore: asyncio.Semaphore,
) -> str:
    """Process one session: fetch intents, call LLM, save. Returns outcome label."""
    async with semaphore:
        intents = await _fetch_tool_call_intents(team_id, session_id)
        if not intents:
            await _save_intent(team_id, session_id, NO_INTENT_RECORDED_FALLBACK)
            return "no_intents"

        summary = await asyncio.to_thread(_summarize_intents_sync, intents)
        if not summary:
            return "llm_skipped"

        await _save_intent(team_id, session_id, summary)
        return "summarised"


@activity.defn(name="summarize-mcp-session-intents")
async def summarize_mcp_session_intents(input: SummarizeMCPSessionIntentsInput) -> None:
    log = logger.bind(activity="summarize-mcp-session-intents")
    tag_queries(product=Product.MCP, feature=Feature.QUERY, name="mcp_session_intent_summary")

    pending = await _take_pending_sessions(input.batch_size, input.idle_minutes)
    log.info(
        "Found sessions awaiting intent summary",
        count=len(pending),
        idle_minutes=input.idle_minutes,
        concurrency=input.concurrency,
    )

    if not pending:
        log.info("MCP session intent summary complete", summarised=0, skipped=0)
        return

    semaphore = asyncio.Semaphore(max(1, input.concurrency))
    outcomes = await asyncio.gather(
        *(_summarise_one(team_id, session_id, semaphore) for team_id, session_id in pending),
        return_exceptions=False,
    )

    summarised = sum(1 for o in outcomes if o == "summarised")
    no_intents = sum(1 for o in outcomes if o == "no_intents")
    llm_skipped = sum(1 for o in outcomes if o == "llm_skipped")

    log.info(
        "MCP session intent summary complete",
        summarised=summarised,
        no_intents=no_intents,
        llm_skipped=llm_skipped,
    )
