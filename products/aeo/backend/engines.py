"""Answer-engine clients for the AEO citation-tracking POC.

Each engine runs one prompt against one answer surface and returns the
citations parsed from the live API response. Parsing must happen here, on the
caller side: the AI gateway's captured $ai_generation events drop web-search
result blocks before emission (only the issued search queries survive into
$ai_output_choices), so the cited URLs exist nowhere except the live response.

Gateway-routed engines stamp X-PostHog-Trace-Id and X-PostHog-Properties so
each check's $ai_generation event (cost, latency, web-search fees) can be
joined back to the prompt via `aeo_prompt_id` / `aeo_run_id`.
"""

from __future__ import annotations

from dataclasses import field
from typing import Any, Protocol
from urllib.parse import urlparse

from django.conf import settings

import requests

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import ai_gateway_headers, resolve_ai_gateway_config

GATEWAY_TIMEOUT_SECONDS = 180  # web-search turns routinely take 10-60s
EXA_TIMEOUT_SECONDS = 60
EXA_ANSWER_URL = "https://api.exa.ai/answer"

# Anthropic's server-side web search tool. The gateway passes server tool
# blocks through unchanged on the native /messages path.
ANTHROPIC_WEB_SEARCH_TOOL_TYPE = "web_search_20260209"
MAX_WEB_SEARCHES_PER_PROMPT = 3
MAX_ANSWER_TOKENS = 2048

# Property-size guards so a single check event stays small.
MAX_URLS_PER_CHECK = 40
MAX_QUERIES_PER_CHECK = 10
MAX_ERROR_LENGTH = 500


@frozen
class CitationCheck:
    """The outcome of running one prompt against one answer engine."""

    engine: str
    model: str
    # URLs the answer actually cites, in first-mention order.
    cited_urls: list[str] = field(default_factory=list)
    # URLs the engine retrieved/saw but didn't necessarily cite (Anthropic only).
    retrieved_urls: list[str] = field(default_factory=list)
    # Search queries the model issued.
    search_queries: list[str] = field(default_factory=list)
    # Engine-reported cost (Exa). Gateway engines report cost on their
    # $ai_generation event instead — join via trace_id.
    cost_usd: float | None = None
    trace_id: str | None = None
    error: str | None = None


class CitationEngine(Protocol):
    name: str
    model: str

    def run(self, prompt: str, *, trace_id: str, custom_properties: dict[str, str]) -> CitationCheck: ...


def _session() -> requests.Session:
    # trust_env=False keeps in-cluster gateway calls off any egress proxy, and
    # the session reuses connections across a run's many sequential calls.
    session = requests.Session()
    session.trust_env = False
    return session


def gateway_post_json(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int = GATEWAY_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """POST and decode JSON; raises requests.RequestException on any failure."""
    response = session.post(url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            result.append(url)
    return result


def parse_anthropic_citations(body: dict[str, Any]) -> tuple[str, list[str], list[str], list[str]]:
    """Parse a non-streaming Anthropic Messages response with web search.

    Returns (answer_text, cited_urls, retrieved_urls, search_queries).
    Cited = citation entries attached to text blocks (what the answer relies
    on); retrieved = web_search_tool_result entries (what the model saw).
    """
    answer_parts: list[str] = []
    cited: list[str] = []
    retrieved: list[str] = []
    queries: list[str] = []

    for block in body.get("content") or []:
        block_type = block.get("type")
        if block_type == "text":
            answer_parts.append(block.get("text") or "")
            for citation in block.get("citations") or []:
                url = citation.get("url")
                if url:
                    cited.append(str(url))
        elif block_type == "server_tool_use" and block.get("name") == "web_search":
            query = (block.get("input") or {}).get("query")
            if query:
                queries.append(str(query))
        elif block_type == "web_search_tool_result":
            content = block.get("content")
            # An errored search's content is an object, not a list — skip it.
            if isinstance(content, list):
                for result in content:
                    if isinstance(result, dict) and result.get("url"):
                        retrieved.append(str(result["url"]))

    return "".join(answer_parts), _dedupe_urls(cited), _dedupe_urls(retrieved), queries


def parse_openai_responses_citations(body: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    """Parse a non-streaming OpenAI Responses API response with web search.

    Returns (answer_text, cited_urls, search_queries). The Responses API does
    not expose the retrieved result list, only url_citation annotations.
    """
    answer_parts: list[str] = []
    cited: list[str] = []
    queries: list[str] = []

    for item in body.get("output") or []:
        item_type = item.get("type")
        if item_type == "web_search_call":
            action = item.get("action")
            query = action.get("query") if isinstance(action, dict) else None
            if query:
                queries.append(str(query))
        elif item_type == "message":
            for content in item.get("content") or []:
                if content.get("type") != "output_text":
                    continue
                answer_parts.append(content.get("text") or "")
                for annotation in content.get("annotations") or []:
                    if annotation.get("type") == "url_citation" and annotation.get("url"):
                        cited.append(str(annotation["url"]))

    return "".join(answer_parts), _dedupe_urls(cited), queries


def parse_exa_citations(body: dict[str, Any]) -> tuple[str, list[str], float | None]:
    """Parse an Exa /answer response. Returns (answer_text, cited_urls, cost_usd)."""
    cited = [str(c["url"]) for c in body.get("citations") or [] if isinstance(c, dict) and c.get("url")]
    cost = body.get("costDollars")
    cost_usd = cost.get("total") if isinstance(cost, dict) else None
    answer = body.get("answer")
    return answer if isinstance(answer, str) else "", _dedupe_urls(cited), cost_usd


def is_target_url(url: str, target_domains: list[str]) -> bool:
    """True when the URL's host is one of the target domains or a subdomain of it."""
    try:
        host = (urlparse(url).netloc or "").lower().split(":")[0]
    except ValueError:
        return False
    return any(host == domain or host.endswith(f".{domain}") for domain in (d.lower() for d in target_domains))


def target_position(cited_urls: list[str], target_domains: list[str]) -> int | None:
    """1-based position of the first target-domain URL in the citation list."""
    for index, url in enumerate(cited_urls, start=1):
        if is_target_url(url, target_domains):
            return index
    return None


def top_domains(urls: list[str]) -> list[str]:
    domains: list[str] = []
    for url in urls:
        try:
            host = (urlparse(url).netloc or "").lower().split(":")[0]
        except ValueError:
            continue
        if host and host not in domains:
            domains.append(host)
    return domains


def build_check_properties(
    *,
    check: CitationCheck,
    run_id: str,
    prompt_id: str,
    prompt_text: str,
    prompt_source: str,
    prompt_hash: str,
    target_domains: list[str],
) -> dict[str, Any]:
    """Event properties for one $aeo_citation_check. Pure, so it's testable.

    Failed checks are captured too — the alerting scout must be able to tell
    "the engine broke" apart from "the citations disappeared".
    """
    target_urls = [url for url in check.cited_urls if is_target_url(url, target_domains)]
    properties: dict[str, Any] = {
        "aeo_run_id": run_id,
        "prompt_id": prompt_id,
        "prompt_text": prompt_text[:500],
        "prompt_source": prompt_source,
        "prompt_hash": prompt_hash,
        "engine": check.engine,
        "model": check.model,
        "check_failed": check.error is not None,
        "cited": bool(target_urls),
        "num_citations": len(check.cited_urls),
        "cited_urls": check.cited_urls[:MAX_URLS_PER_CHECK],
        "retrieved_urls": check.retrieved_urls[:MAX_URLS_PER_CHECK],
        "search_queries": check.search_queries[:MAX_QUERIES_PER_CHECK],
        "target_urls": target_urls[:MAX_URLS_PER_CHECK],
        "target_best_position": target_position(check.cited_urls, target_domains),
        "top_cited_domains": top_domains(check.cited_urls)[:MAX_URLS_PER_CHECK],
    }
    if check.error is not None:
        properties["error"] = check.error[:MAX_ERROR_LENGTH]
    if check.cost_usd is not None:
        properties["cost_usd"] = check.cost_usd
    if check.trace_id is not None:
        properties["gateway_trace_id"] = check.trace_id
    return properties


def _request_error(e: requests.RequestException) -> str:
    detail = ""
    if e.response is not None:
        detail = f" status={e.response.status_code} body={e.response.text[:200]}"
    return f"{type(e).__name__}:{detail or ' ' + str(e)[:200]}"


class ClaudeWebSearchEngine:
    """Claude with Anthropic's native web_search server tool, via the AI gateway."""

    name = "claude-web-search"

    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.AEO_ANTHROPIC_MODEL
        gateway = resolve_ai_gateway_config()
        if gateway is None:
            raise ValueError("AI gateway is not configured (AI_GATEWAY_URL / AI_GATEWAY_API_KEY)")
        self._gateway = gateway
        self._session = _session()

    def run(self, prompt: str, *, trace_id: str, custom_properties: dict[str, str]) -> CitationCheck:
        payload = {
            "model": self.model,
            "max_tokens": MAX_ANSWER_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [
                {
                    "type": ANTHROPIC_WEB_SEARCH_TOOL_TYPE,
                    "name": "web_search",
                    "max_uses": MAX_WEB_SEARCHES_PER_PROMPT,
                }
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._gateway.api_key}",
            "anthropic-version": "2023-06-01",
            **(ai_gateway_headers(trace_id=trace_id, properties=custom_properties) or {}),
        }
        try:
            body = gateway_post_json(self._session, self._gateway.url.rstrip("/") + "/messages", headers, payload)
        except requests.RequestException as e:
            return CitationCheck(engine=self.name, model=self.model, trace_id=trace_id, error=_request_error(e))
        _, cited_urls, retrieved_urls, search_queries = parse_anthropic_citations(body)
        return CitationCheck(
            engine=self.name,
            model=self.model,
            trace_id=trace_id,
            cited_urls=cited_urls,
            retrieved_urls=retrieved_urls,
            search_queries=search_queries,
        )


class OpenAIWebSearchEngine:
    """An OpenAI model with its web search tool, via the AI gateway's /responses path."""

    name = "openai-web-search"

    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.AEO_OPENAI_MODEL
        gateway = resolve_ai_gateway_config()
        if gateway is None:
            raise ValueError("AI gateway is not configured (AI_GATEWAY_URL / AI_GATEWAY_API_KEY)")
        self._gateway = gateway
        self._session = _session()

    def run(self, prompt: str, *, trace_id: str, custom_properties: dict[str, str]) -> CitationCheck:
        payload = {
            "model": self.model,
            "input": prompt,
            "tools": [{"type": "web_search"}],
            "max_output_tokens": MAX_ANSWER_TOKENS,
        }
        headers = {
            "Authorization": f"Bearer {self._gateway.api_key}",
            **(ai_gateway_headers(trace_id=trace_id, properties=custom_properties) or {}),
        }
        try:
            body = gateway_post_json(self._session, self._gateway.url.rstrip("/") + "/responses", headers, payload)
        except requests.RequestException as e:
            return CitationCheck(engine=self.name, model=self.model, trace_id=trace_id, error=_request_error(e))
        _, cited_urls, search_queries = parse_openai_responses_citations(body)
        return CitationCheck(
            engine=self.name,
            model=self.model,
            trace_id=trace_id,
            cited_urls=cited_urls,
            search_queries=search_queries,
        )


class ExaAnswerEngine:
    """Exa /answer — a cheap search-API proxy for answer-engine citation behavior.

    Its citations are Exa's own, not ChatGPT's or Claude's; useful as a
    retrievability check and as a comparison baseline against the real models.
    Called directly at POC volume (tens of calls/day); move behind a
    posthog/egress incarnation if this graduates to real rollout.
    """

    name = "exa-answer"
    model = "exa-answer"

    def __init__(self) -> None:
        self._session = requests.Session()

    def run(self, prompt: str, *, trace_id: str, custom_properties: dict[str, str]) -> CitationCheck:
        headers = {"x-api-key": settings.EXA_API_KEY}
        try:
            body = gateway_post_json(
                self._session,
                EXA_ANSWER_URL,
                headers,
                {"query": prompt, "text": False},
                timeout=EXA_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            return CitationCheck(engine=self.name, model=self.model, error=_request_error(e))
        _, cited_urls, cost_usd = parse_exa_citations(body)
        return CitationCheck(engine=self.name, model=self.model, cited_urls=cited_urls, cost_usd=cost_usd)


def available_engines() -> list[CitationEngine]:
    """Engines the current configuration supports."""
    engines: list[CitationEngine] = []
    if resolve_ai_gateway_config() is not None:
        engines.append(ClaudeWebSearchEngine())
        engines.append(OpenAIWebSearchEngine())
    if settings.EXA_API_KEY:
        engines.append(ExaAnswerEngine())
    return engines
