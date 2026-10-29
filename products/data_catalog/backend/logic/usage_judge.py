"""Ask a model whether an agent query computes a catalog metric.

A shared measure fingerprint only nominates a pair. Two queries can share tables, aggregate and
filters and still answer different questions, so a judge reads the intent and decides.
"""

import re
import json
from typing import Literal

import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field, ValidationError

from posthog.dataclasses import frozen

from ..facade.enums import JudgeRelation

logger = structlog.get_logger(__name__)

JUDGE_MODEL = "claude-opus-5-5"

# Bounds one call's input. A definition or a query longer than this is rare, and the start of it
# carries the tables, the aggregate and the filters the judge needs.
_MAX_FIELD_CHARS = 8000

_SYSTEM_PROMPT = """You review how AI agents answer data questions for a team that keeps a catalog of approved metric definitions.

You get one catalog metric and one SQL query an agent ran, with the question the agent said it was answering.
Decide how the query relates to the metric:

- "serves": the query computes the metric's measure for the agent's question. A different time range, grain, grouping, sort order or row limit still serves.
- "slice": the query computes the metric's measure, restricted by an extra filter the metric does not have, for example one plan, one country or one event property.
- "different": the query computes a different measure, or serves a different purpose, even when it reads the same tables.

Reply with one JSON object and nothing else, in this key order:
{"reasoning": "<two or three sentences>", "relation": "serves" | "slice" | "different", "confidence": <number from 0 to 1>}"""

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


@frozen
class MetricBrief:
    """The part of a catalog metric the judge reads."""

    name: str
    description: str
    definition: str


@frozen
class JudgeVerdict:
    relation: JudgeRelation
    confidence: float
    reasoning: str


class _JudgeReply(BaseModel):
    reasoning: str
    relation: Literal["serves", "slice", "different"]
    confidence: float = Field(ge=0, le=1)


def build_judge_prompt(metric: MetricBrief, intent: str, sql: str) -> str:
    return (
        f"Metric name: {metric.name}\n"
        f"Metric description: {metric.description[:_MAX_FIELD_CHARS]}\n"
        f"Metric definition:\n{metric.definition[:_MAX_FIELD_CHARS]}\n\n"
        f"Agent question: {intent[:_MAX_FIELD_CHARS] or '(not given)'}\n"
        f"Agent SQL:\n{sql[:_MAX_FIELD_CHARS]}"
    )


async def judge_pair(client: AsyncAnthropic, metric: MetricBrief, intent: str, sql: str) -> JudgeVerdict:
    """The judge's verdict, or ``different`` when the call or the reply fails.

    A failure never guesses a match, so a broken judge can only undercount re-derivations.
    """
    try:
        response = await client.messages.create(
            model=JUDGE_MODEL,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_judge_prompt(metric, intent, sql)}],
            max_tokens=1024,
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return parse_judge_reply(text)
    except Exception as error:
        logger.warning("data_catalog_usage_judge_failed", metric=metric.name, error=str(error))
        return JudgeVerdict(relation=JudgeRelation.DIFFERENT, confidence=0.0, reasoning="The judge call failed.")


def parse_judge_reply(text: str) -> JudgeVerdict:
    match = _JSON_OBJECT.search(text)
    try:
        if match is None:
            raise ValueError("no JSON object in the reply")
        reply = _JudgeReply.model_validate(json.loads(match.group(0)))
    except (ValueError, ValidationError) as error:
        logger.warning("data_catalog_usage_judge_unparseable", error=str(error))
        return JudgeVerdict(
            relation=JudgeRelation.DIFFERENT, confidence=0.0, reasoning="The judge reply was unreadable."
        )
    return JudgeVerdict(relation=JudgeRelation(reply.relation), confidence=reply.confidence, reasoning=reply.reasoning)
