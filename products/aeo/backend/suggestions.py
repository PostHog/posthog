"""Suggest prompts for a team's AEO prompt set with Claude, through the AI gateway.

Suggestions are never saved here. A person reviews them and imports the ones they keep,
so every prompt the runner sends to an engine is still one a person chose.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from django.conf import settings

import requests
import structlog

from posthog.llm.gateway_client import ai_gateway_headers, resolve_ai_gateway_config
from posthog.security.llm_prompt_sanitization import sanitize_user_text

from products.aeo.backend.engines import ANTHROPIC_WEB_SEARCH_TOOL_TYPE, MAX_PROMPT_LENGTH
from products.aeo.backend.facade.contracts import (
    PROMPT_TOPIC_MAX_LENGTH,
    FunnelStage,
    PromptCircle,
    PromptSuggestion,
    PromptSuggestionError,
    PromptSuggestionRequest,
)
from products.aeo.backend.seeding import normalize_prompt

logger = structlog.get_logger(__name__)

MAX_SUGGESTIONS = 50
MAX_SUGGESTION_SEARCHES = 3
MAX_SUGGESTION_TOKENS = 8000
MAX_EXISTING_PROMPTS_IN_INSTRUCTIONS = 100
REASON_MAX_LENGTH = 300
# The call runs inside a web request, so it gets one bounded attempt and no retries.
SUGGESTION_TIMEOUT_SECONDS = 90


_INSTRUCTIONS = """You help a team choose the prompts to track for AI visibility: the questions people ask AI assistants \
like ChatGPT and Claude, where the team wants its site to be mentioned and cited.

Research first. Use web search to read {domain} (its homepage, product and pricing pages) and, if given, the \
competitors' sites, so you understand who the product is for and what it does differently.

Then write {count} prompts that a real buyer would type into an AI assistant. Follow these rules:
- Write each prompt the way a person asks it, in full sentences, not as a search keyword.
- Weight toward prompts where someone is choosing a tool, comparing options or solving a concrete problem. \
Keep only a few prompts about learning a concept.
- Most prompts must not name {brand_name}. Add at most {branded_max} branded prompts, such as "what is {brand_name}" \
or "{brand_name} vs <competitor>"; those check how accurately assistants describe the brand.
- Never write a prompt rigged in the brand's favor, such as one that lists a feature only this brand has.
- Only write questions people plausibly ask. Skip niche wording nobody would type.
- Spread the prompts across the topics. Keep each topic to two or three words.

Label every prompt with its circle, from where the buyer, the brand and its competitors overlap:
- differentiation: a need the buyer has that this brand meets and competitors do not.
- battleground: a need the buyer has that this brand and its competitors all meet.
- vulnerability: a need the buyer has that competitors meet better than this brand.
- table_stakes: something every tool in the category does.
- branded: the prompt names the brand.
And with its funnel stage: top (learning), middle (comparing options) or bottom (choosing or buying).

Brand: {brand}
Site: {domain}
What it does and who it is for: {description}
Competitors: {competitors}
Topics to cover: {topics}
Prompts the team already tracks, which you must not repeat or rephrase:
{existing}

Answer with only a JSON array, no other text. Each item has these keys:
"prompt" (string), "topic" (string), "circle" (one of {circles}), "funnel_stage" (one of {stages}), \
"branded" (true or false), "reason" (one short sentence on why a buyer asks this)."""


def _plain(value: str, max_len: int) -> str:
    return sanitize_user_text(value, max_len)


def build_suggestion_instructions(request: PromptSuggestionRequest, existing_prompts: list[str]) -> str:
    count = min(max(request.count, 1), MAX_SUGGESTIONS)
    brand = _plain(request.brand, 200)
    existing = [_plain(prompt, MAX_PROMPT_LENGTH) for prompt in existing_prompts[:MAX_EXISTING_PROMPTS_IN_INSTRUCTIONS]]
    return _INSTRUCTIONS.format(
        domain=_plain(request.domain, 200),
        count=count,
        brand=brand or "infer it from the site",
        brand_name=brand or "the brand",
        branded_max=max(1, count // 5),
        description=_plain(request.description, 1000) or "infer it from the site",
        competitors=", ".join(_plain(c, 200) for c in request.competitors) or "infer the main ones",
        topics=", ".join(_plain(t, PROMPT_TOPIC_MAX_LENGTH) for t in request.topics) or "choose 3 to 6 topics",
        existing="\n".join(f"- {prompt}" for prompt in existing) or "- none",
        circles=", ".join(PromptCircle.values),
        stages=", ".join(FunnelStage.values),
    )


def _json_array(text: str) -> list[Any]:
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end < start:
        raise PromptSuggestionError("The model did not return a list of prompts")
    try:
        items = json.loads(text[start : end + 1])
    except json.JSONDecodeError as error:
        raise PromptSuggestionError("The model returned prompts that could not be read") from error
    if not isinstance(items, list):
        raise PromptSuggestionError("The model did not return a list of prompts")
    return items


def parse_suggestions(text: str, *, count: int, existing_prompts: list[str]) -> list[PromptSuggestion]:
    """Turn the model's answer into suggestions, dropping malformed items, duplicates and prompts
    the team already tracks. The model read third-party pages, so every string is sanitized."""
    seen = {normalize_prompt(prompt).lower() for prompt in existing_prompts}
    suggestions: list[PromptSuggestion] = []
    for item in _json_array(text):
        if not isinstance(item, dict):
            continue
        prompt = normalize_prompt(_plain(str(item.get("prompt") or ""), MAX_PROMPT_LENGTH))
        if not prompt or prompt.lower() in seen:
            continue
        circle = str(item.get("circle") or "")
        stage = str(item.get("funnel_stage") or "")
        if circle not in PromptCircle.values or stage not in FunnelStage.values:
            continue
        seen.add(prompt.lower())
        suggestions.append(
            PromptSuggestion(
                prompt=prompt,
                topic=_plain(str(item.get("topic") or ""), PROMPT_TOPIC_MAX_LENGTH),
                circle=PromptCircle(circle),
                funnel_stage=FunnelStage(stage),
                branded=item.get("branded") is True or circle == PromptCircle.BRANDED,
                reason=_plain(str(item.get("reason") or ""), REASON_MAX_LENGTH),
            )
        )
        if len(suggestions) >= count:
            break
    return suggestions


def _answer_text(body: dict[str, Any]) -> str:
    return "".join(
        block.get("text", "")
        for block in body.get("content") or []
        if isinstance(block, dict) and block.get("type") == "text"
    )


def suggest_prompts(
    team_id: int, request: PromptSuggestionRequest, existing_prompts: list[str]
) -> list[PromptSuggestion]:
    gateway = resolve_ai_gateway_config()
    if gateway is None:
        raise PromptSuggestionError("Prompt suggestions are not available on this instance")
    count = min(max(request.count, 1), MAX_SUGGESTIONS)
    payload = {
        "model": settings.AEO_ANTHROPIC_MODEL,
        "max_tokens": MAX_SUGGESTION_TOKENS,
        "messages": [{"role": "user", "content": build_suggestion_instructions(request, existing_prompts)}],
        "tools": [
            {
                "type": ANTHROPIC_WEB_SEARCH_TOOL_TYPE,
                "name": "web_search",
                "max_uses": MAX_SUGGESTION_SEARCHES,
                "allowed_callers": ["direct"],
            }
        ],
    }
    headers = {
        "Authorization": f"Bearer {gateway.api_key}",
        "anthropic-version": "2023-06-01",
        **(
            ai_gateway_headers(
                trace_id=str(uuid.uuid4()),
                properties={"team_id": str(team_id), "aeo_feature": "prompt_suggestions"},
            )
            or {}
        ),
    }
    try:
        with requests.Session() as session:
            # Keep the in-cluster gateway call off any egress proxy, as the engines do.
            session.trust_env = False
            response = session.post(
                gateway.url.rstrip("/") + "/messages",
                headers=headers,
                json=payload,
                timeout=SUGGESTION_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            body = response.json()
    except (requests.RequestException, ValueError) as error:
        logger.warning("aeo_prompt_suggestions_failed", team_id=team_id, error=type(error).__name__)
        raise PromptSuggestionError("Prompt suggestions failed. Try again in a minute.") from error
    return parse_suggestions(_answer_text(body), count=count, existing_prompts=existing_prompts)
