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

import re
from dataclasses import field
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlparse

from django.conf import settings

import requests
import structlog
from celery.exceptions import SoftTimeLimitExceeded
from google.genai import (
    errors as genai_errors,
    types as genai_types,
)

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import ai_gateway_headers, build_gemini_client, resolve_ai_gateway_config
from posthog.security.llm_prompt_sanitization import (
    GENERIC_VALUE_MAX_LEN,
    sanitize_user_text,
    strip_llm_framing_markers,
)

from products.aeo.backend.facade.contracts import AEO_GEMINI_ENGINE_FLAG
from products.aeo.backend.flags import aeo_flag_enabled

if TYPE_CHECKING:
    from posthog.models.team import Team

logger = structlog.get_logger(__name__)

GATEWAY_TIMEOUT_SECONDS = 420  # web-search turns routinely take 10-60s, and multi-search answers several minutes
# The gateway drops a Gemini request at its own 290s header timeout, so a longer client wait only outlives it.
GEMINI_TIMEOUT_MS = 290_000
EXA_TIMEOUT_SECONDS = 60
EXA_ANSWER_URL = "https://api.exa.ai/answer"

# Anthropic's server-side web search tool. The gateway passes server tool
# blocks through unchanged on the native /messages path.
ANTHROPIC_WEB_SEARCH_TOOL_TYPE = "web_search_20260209"
MAX_WEB_SEARCHES_PER_PROMPT = 3
MAX_ANSWER_TOKENS = 4096
# Reasoning models spend output budget on reasoning before emitting the annotated
# answer; too small a cap yields incomplete, citation-less responses that would
# otherwise read as "not cited".
OPENAI_MAX_OUTPUT_TOKENS = 12000

AEO_AI_PRODUCT = "aeo"
# The Gemini API grounding chunk carries this redirect host as its uri and the
# source domain in its `domain` field.
GEMINI_GROUNDING_REDIRECT_HOST = "vertexaisearch.cloud.google.com"
_BARE_DOMAIN = re.compile(r"^(?=.{1,253}$)[a-z0-9-]{1,63}(\.[a-z0-9-]{1,63})+$")

# Property-size guards so a single check event stays small.
MAX_URLS_PER_CHECK = 40
MAX_QUERIES_PER_CHECK = 10
MAX_ERROR_LENGTH = 500
MAX_ANSWER_TEXT_LENGTH = 8000
# Longest prompt seeding will keep and a check event will record. Above the
# signup free-text limit, so no real user-reported prompt is dropped, and far
# below anything that would inflate an engine call. Seeding imports this, so the
# recorded prompt_text is always the whole prompt that ran.
MAX_PROMPT_LENGTH = 2000


@frozen
class CitationCheck:
    """The outcome of running one prompt against one answer engine."""

    engine: str
    model: str
    # URLs the answer actually cites, in first-mention order.
    cited_urls: list[str] = field(default_factory=list)
    # URLs the engine retrieved/saw but didn't necessarily cite (Anthropic and Gemini only).
    retrieved_urls: list[str] = field(default_factory=list)
    # Search queries the model issued.
    search_queries: list[str] = field(default_factory=list)
    answer_text: str = ""
    # Engine-reported cost (Exa). Gateway engines report cost on their
    # $ai_generation event instead — join via trace_id.
    cost_usd: float | None = None
    trace_id: str | None = None
    error: str | None = None


@frozen
class ParsedAnswer:
    """What one engine's raw response yields once parsed.

    Each engine fills only the fields its API exposes: the Responses API has no
    retrieved-result list, and only Exa reports a per-call cost.
    """

    answer_text: str = ""
    cited_urls: list[str] = field(default_factory=list)
    retrieved_urls: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    cost_usd: float | None = None
    # Gemini grounding chunks whose redirect could not be mapped back to a source domain (Gemini only).
    unresolved_chunks: int = 0
    unresolved_cited_chunks: int = 0


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


def parse_anthropic_citations(body: dict[str, Any]) -> ParsedAnswer:
    """Parse a non-streaming Anthropic Messages response with web search.

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

    return ParsedAnswer(
        answer_text="".join(answer_parts),
        cited_urls=_dedupe_urls(cited),
        retrieved_urls=_dedupe_urls(retrieved),
        search_queries=queries,
    )


def parse_openai_responses_citations(body: dict[str, Any]) -> ParsedAnswer:
    """Parse a non-streaming OpenAI Responses API response with web search.

    The Responses API does not expose the retrieved result list, only
    url_citation annotations.
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

    return ParsedAnswer(answer_text="".join(answer_parts), cited_urls=_dedupe_urls(cited), search_queries=queries)


def _has_answer_text(body: dict[str, Any]) -> bool:
    """True when the body carries at least one non-empty output_text block, which is
    the only part of a Responses body that can carry an answer and its citations."""
    for item in body.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and content.get("text"):
                return True
    return False


def openai_response_error(body: dict[str, Any]) -> str | None:
    """A Responses body that reports a non-completed status and produced no answer text
    did not answer (budget exhausted, failed, or cancelled). That is a failed check, not
    a zero-citation answer, so the scout can tell "the engine broke" from "the citations
    disappeared". An empty message item is not an answer, so it counts as neither."""
    status = body.get("status")
    if status in (None, "completed"):
        return None
    if _has_answer_text(body):
        return None
    # 'incomplete' carries incomplete_details.reason; 'failed' carries error.message.
    details = body.get("incomplete_details") or body.get("error")
    reason = (details.get("reason") or details.get("message")) if isinstance(details, dict) else None
    return f"{status}_response: {reason or 'unknown'}"


def anthropic_truncated_error(body: dict[str, Any], cited_urls: list[str]) -> str | None:
    """A Messages body cut off at max_tokens before any citation did not finish
    answering. Treat it as a failed check rather than a zero-citation answer, the
    same way openai_response_error handles a budget-exhausted Responses body."""
    if body.get("stop_reason") == "max_tokens" and not cited_urls:
        return "max_tokens_response: truncated before citing"
    return None


def parse_exa_citations(body: dict[str, Any]) -> ParsedAnswer:
    """Parse an Exa /answer response."""
    cited = [str(c["url"]) for c in body.get("citations") or [] if isinstance(c, dict) and c.get("url")]
    cost = body.get("costDollars")
    answer = body.get("answer")
    return ParsedAnswer(
        answer_text=answer if isinstance(answer, str) else "",
        cited_urls=_dedupe_urls(cited),
        cost_usd=cost.get("total") if isinstance(cost, dict) else None,
    )


def _gemini_chunk_url(web: genai_types.GroundingChunkWeb) -> str | None:
    """None means the chunk has no uri or a grounding redirect, and names no source domain."""
    uri = web.uri or ""
    try:
        host = (urlparse(uri).hostname or "").lower()
    except ValueError:
        host = ""
    if uri and host != GEMINI_GROUNDING_REDIRECT_HOST:
        return uri
    # is_target_url matches on host, so a redirect uri never counts as a citation of the
    # source. Record the source domain from the chunk instead of following the redirect.
    # The title is the page's own text, so a third-party page titled like a target
    # domain would forge a citation; only the SDK's domain field names the source.
    domain = (web.domain or "").strip().lower()
    if _BARE_DOMAIN.match(domain):
        return f"https://{domain}"
    return None


def parse_gemini_grounding(response: genai_types.GenerateContentResponse) -> ParsedAnswer:
    """Parse a generate_content response grounded with Google Search.

    Retrieved = every grounding chunk; cited = the chunks a grounding support
    attaches to a span of the answer, in first-reference order. A redirect chunk
    that names no source domain is dropped and counted in unresolved_chunks, and
    in unresolved_cited_chunks when a support cites it, so the engine can fail the
    check instead of recording a redirect URL nothing matches.
    """
    candidate = response.candidates[0] if response.candidates else None
    if candidate is None:
        return ParsedAnswer()
    parts = candidate.content.parts if candidate.content and candidate.content.parts else []
    answer_text = "".join(part.text for part in parts if part.text and not part.thought)

    metadata = candidate.grounding_metadata
    if metadata is None:
        return ParsedAnswer(answer_text=answer_text)
    chunks = metadata.grounding_chunks or []
    # Positional, so a support's chunk index still lands on the right chunk.
    chunk_urls = [_gemini_chunk_url(chunk.web) if chunk.web is not None else None for chunk in chunks]
    cited: list[str] = []
    cited_indices: set[int] = set()
    for support in metadata.grounding_supports or []:
        for index in support.grounding_chunk_indices or []:
            if 0 <= index < len(chunk_urls):
                cited_indices.add(index)
                if url := chunk_urls[index]:
                    cited.append(url)
    unresolved = {index for index, chunk in enumerate(chunks) if chunk.web is not None and chunk_urls[index] is None}

    return ParsedAnswer(
        answer_text=answer_text,
        cited_urls=_dedupe_urls(cited),
        retrieved_urls=_dedupe_urls([url for url in chunk_urls if url]),
        search_queries=list(metadata.web_search_queries or []),
        unresolved_chunks=len(unresolved),
        unresolved_cited_chunks=len(unresolved & cited_indices),
    )


def gemini_response_error(response: genai_types.GenerateContentResponse, cited_urls: list[str]) -> str | None:
    """A response that never answered is a failed check, not a zero-citation answer:
    no candidate (the prompt was blocked), a candidate without content, or a candidate
    that stopped for a reason other than STOP (safety, recitation, max tokens) before
    citing anything, the same way anthropic_truncated_error treats a cut-off answer."""
    if not response.candidates:
        feedback = response.prompt_feedback
        block_reason = feedback.block_reason if feedback is not None else None
        return f"no_candidates_response: {block_reason.value if block_reason is not None else 'unknown'}"
    candidate = response.candidates[0]
    finish_reason = candidate.finish_reason
    reason = finish_reason.value.lower() if finish_reason is not None else "unknown"
    if candidate.content is None:
        return f"{reason}_response: no content"
    if finish_reason in (None, genai_types.FinishReason.STOP) or cited_urls:
        return None
    return f"{reason}_response: {candidate.finish_message or 'stopped before citing'}"


def gemini_unresolved_error(parsed: ParsedAnswer) -> str | None:
    """A cited chunk that is a redirect naming no source domain may well be us, so
    the check cannot tell whether the answer cited us. The same holds when every
    chunk is unresolved, cited or not. Both are a failed check, not a zero-citation
    answer."""
    if parsed.unresolved_cited_chunks or (parsed.unresolved_chunks and not parsed.retrieved_urls):
        return (
            f"unresolved_grounding_redirects: {parsed.unresolved_chunks} chunks, {parsed.unresolved_cited_chunks} cited"
        )
    return None


def is_target_url(url: str, target_domains: list[str]) -> bool:
    """True when the URL's host is one of the target domains or a subdomain of it."""
    try:
        host = (urlparse(url).hostname or "").lower()
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
            host = (urlparse(url).hostname or "").lower()
        except ValueError:
            continue
        if host and host not in domains:
            domains.append(host)
    return domains


def _safe_values(values: list[str], *, limit: int = MAX_URLS_PER_CHECK) -> list[str]:
    """Strip invisible characters and LLM framing markers from engine-derived strings.

    URLs, search queries and provider error bodies are third-party text, and the
    alerting scout reads them, so they reach an LLM. Sanitize before recording,
    the same way AI subscriptions sanitize user-controlled event names.
    """
    cleaned = (sanitize_user_text(value, GENERIC_VALUE_MAX_LEN) for value in values[:limit])
    return [value for value in cleaned if value]


def build_check_fields(
    *,
    check: CitationCheck,
    run_id: str,
    prompt_id: str,
    prompt_text: str,
    prompt_source: str,
    prompt_hash: str,
    target_domains: list[str],
) -> dict[str, Any]:
    """Column values for one AEOCitationCheck row. Pure, so it's testable.

    Failed checks are recorded too — the alerting scout must be able to tell
    "the engine broke" apart from "the citations disappeared".
    """
    target_urls = [url for url in check.cited_urls if is_target_url(url, target_domains)]
    return {
        "run_id": run_id,
        "prompt_id": prompt_id,
        "prompt_text": sanitize_user_text(prompt_text, MAX_PROMPT_LENGTH),
        "prompt_source": prompt_source,
        "prompt_hash": prompt_hash,
        "engine": check.engine,
        "model": check.model,
        "check_failed": check.error is not None,
        "error": sanitize_user_text(check.error, MAX_ERROR_LENGTH) if check.error is not None else None,
        "cited": bool(target_urls),
        "num_citations": len(check.cited_urls),
        "cited_urls": _safe_values(check.cited_urls),
        "retrieved_urls": _safe_values(check.retrieved_urls),
        "search_queries": _safe_values(check.search_queries, limit=MAX_QUERIES_PER_CHECK),
        "answer_text": strip_llm_framing_markers(check.answer_text, MAX_ANSWER_TEXT_LENGTH) or None,
        "target_urls": _safe_values(target_urls),
        "target_best_position": target_position(check.cited_urls, target_domains),
        "top_cited_domains": _safe_values(top_domains(check.cited_urls)),
        "cost_usd": check.cost_usd,
        "gateway_trace_id": check.trace_id,
    }


def _request_error(e: requests.RequestException) -> str:
    detail = ""
    if e.response is not None:
        detail = f" status={e.response.status_code} body={e.response.text[:200]}"
    return f"{type(e).__name__}:{detail or ' ' + str(e)[:200]}"


def _gemini_request_error(e: genai_errors.APIError) -> str:
    return f"{type(e).__name__}: status={e.code} body={(e.message or '')[:200]}"


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
                    # This tool version runs searches from code execution by default. Claude then reads
                    # the results through encrypted stdout, and the answer text carries no citations.
                    # Direct calls attach web_search_result_location citations, and they keep the tool
                    # eligible for zero data retention.
                    "allowed_callers": ["direct"],
                }
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._gateway.api_key}",
            "anthropic-version": "2023-06-01",
            **(ai_gateway_headers(ai_product=AEO_AI_PRODUCT, trace_id=trace_id, properties=custom_properties) or {}),
        }
        try:
            body = gateway_post_json(self._session, self._gateway.url.rstrip("/") + "/messages", headers, payload)
        except requests.RequestException as e:
            return CitationCheck(engine=self.name, model=self.model, trace_id=trace_id, error=_request_error(e))
        parsed = parse_anthropic_citations(body)
        if (truncated := anthropic_truncated_error(body, parsed.cited_urls)) is not None:
            return CitationCheck(engine=self.name, model=self.model, trace_id=trace_id, error=truncated)
        return CitationCheck(
            engine=self.name,
            model=self.model,
            trace_id=trace_id,
            cited_urls=parsed.cited_urls,
            retrieved_urls=parsed.retrieved_urls,
            search_queries=parsed.search_queries,
            answer_text=parsed.answer_text,
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
            "max_output_tokens": OPENAI_MAX_OUTPUT_TOKENS,
        }
        headers = {
            "Authorization": f"Bearer {self._gateway.api_key}",
            **(ai_gateway_headers(ai_product=AEO_AI_PRODUCT, trace_id=trace_id, properties=custom_properties) or {}),
        }
        try:
            body = gateway_post_json(self._session, self._gateway.url.rstrip("/") + "/responses", headers, payload)
        except requests.RequestException as e:
            return CitationCheck(engine=self.name, model=self.model, trace_id=trace_id, error=_request_error(e))
        if (error := openai_response_error(body)) is not None:
            return CitationCheck(engine=self.name, model=self.model, trace_id=trace_id, error=error)
        parsed = parse_openai_responses_citations(body)
        return CitationCheck(
            engine=self.name,
            model=self.model,
            trace_id=trace_id,
            cited_urls=parsed.cited_urls,
            search_queries=parsed.search_queries,
            answer_text=parsed.answer_text,
        )


class GeminiGroundedEngine:
    """Gemini grounded with Google Search, via the AI gateway's generateContent path."""

    name = "gemini-google-search"

    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.AEO_GEMINI_MODEL
        if resolve_ai_gateway_config() is None:
            raise ValueError("AI gateway is not configured (AI_GATEWAY_URL / AI_GATEWAY_API_KEY)")

    def run(self, prompt: str, *, trace_id: str, custom_properties: dict[str, str]) -> CitationCheck:
        # The client carries the trace and property headers, so each check builds its own
        # and closes its connection pool when the check ends.
        client = build_gemini_client(
            ai_product=AEO_AI_PRODUCT,
            trace_id=trace_id,
            properties=custom_properties,
            timeout_ms=GEMINI_TIMEOUT_MS,
        )
        if client is None:
            return CitationCheck(engine=self.name, model=self.model, trace_id=trace_id, error="ai_gateway_unset")
        config = genai_types.GenerateContentConfig(
            tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
            max_output_tokens=MAX_ANSWER_TOKENS,
        )
        try:
            with client:
                response = client.models.generate_content(model=self.model, contents=prompt, config=config)
        except genai_errors.APIError as e:
            return CitationCheck(engine=self.name, model=self.model, trace_id=trace_id, error=_gemini_request_error(e))
        except SoftTimeLimitExceeded:
            # Celery raises this inside whatever call is in flight. Swallowing it as a failed
            # check would let the scheduled run keep making billed calls past its soft limit.
            raise
        except Exception as e:
            # The SDK raises plain ValueError and pydantic errors on a malformed 2xx body, and
            # the gateway client raises its own host error. One escaped exception would abort
            # the whole run, so every failure becomes a failed check row instead.
            return CitationCheck(
                engine=self.name, model=self.model, trace_id=trace_id, error=f"{type(e).__name__}: {str(e)[:200]}"
            )
        parsed = parse_gemini_grounding(response)
        if parsed.unresolved_chunks:
            logger.warning(
                "aeo_gemini_unresolved_grounding_redirects",
                unresolved=parsed.unresolved_chunks,
                unresolved_cited=parsed.unresolved_cited_chunks,
                resolved=len(parsed.retrieved_urls),
                trace_id=trace_id,
            )
        error = gemini_response_error(response, parsed.cited_urls) or gemini_unresolved_error(parsed)
        if error is not None:
            return CitationCheck(engine=self.name, model=self.model, trace_id=trace_id, error=error)
        return CitationCheck(
            engine=self.name,
            model=self.model,
            trace_id=trace_id,
            cited_urls=parsed.cited_urls,
            retrieved_urls=parsed.retrieved_urls,
            search_queries=parsed.search_queries,
            answer_text=parsed.answer_text,
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
        parsed = parse_exa_citations(body)
        return CitationCheck(
            engine=self.name,
            model=self.model,
            cited_urls=parsed.cited_urls,
            answer_text=parsed.answer_text,
            cost_usd=parsed.cost_usd,
        )


def available_engines(team: Team) -> list[CitationEngine]:
    """Engines the current configuration supports for a scheduled run of this team."""
    engines: list[CitationEngine] = []
    if resolve_ai_gateway_config() is not None:
        engines.append(ClaudeWebSearchEngine())
        engines.append(OpenAIWebSearchEngine())
        if aeo_flag_enabled(AEO_GEMINI_ENGINE_FLAG, team):
            engines.append(GeminiGroundedEngine())
    if settings.EXA_API_KEY:
        engines.append(ExaAnswerEngine())
    return engines
