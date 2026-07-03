"""Reusable core for LLM-drafted semantic descriptions.

Warehouse table enrichment and data-modeling view enrichment both draft one-sentence descriptions of
data assets so PostHog AI picks the right tables/columns and joins. The surface-specific orchestration
(what to enrich, how to build the prompt, where to persist) lives with each product; the pieces shared
by both — prompt-injection hardening, the JSON completion + parsing, the feature-flag/consent gates,
telemetry, the team's business context, and the guarded annotation upsert — live here.

This module deliberately has zero warehouse- or data-modeling-model dependencies: `upsert_column_annotation`
takes the annotation model class and its owner fields as arguments so one code path serves both
`WarehouseColumnAnnotation` and `DataWarehouseSavedQueryColumnAnnotation` (identical fields, both
`TeamScopedRootMixin`).
"""

import re
import json
from collections.abc import Callable
from typing import Any

from django.utils import timezone

import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.helpers.tiktoken_encoding import LLM_TOKEN_COUNT_PROXY_MODEL, get_tiktoken_encoding_for_model
from posthog.llm.gateway_client import Product, get_llm_client
from posthog.models import Team

DEFAULT_ENRICHMENT_MODEL = "claude-haiku-4-5"
# Keep the prompt and response bounded — wide tables shouldn't blow up the context or the cost.
MAX_COLUMNS_PER_TABLE = 200
# The team's core memory is free-form and unbounded; a large dump alone can push the prompt past the
# model's 200k-token context window. Cap it — a concise company summary is all the enrichment needs.
MAX_BUSINESS_CONTEXT_CHARS = 20_000
# Last-resort ceiling on the whole assembled prompt, measured in tokens against the model's 200k-token
# input window with headroom left for the response. A char-based budget can't hold this ceiling: the
# prompt is dominated by structured identifiers/types and can carry non-English business context, both
# of which tokenize far denser than the ~3-4 chars/token of English prose — so a "safe" char count can
# still blow past 200k tokens. If the prompt exceeds this after capping the business context, we drop
# columns from the tail until it fits; enrichment is idempotent, so a later pass fills in what we skip.
MAX_PROMPT_TOKENS = 150_000

_WHITESPACE_RE = re.compile(r"\s+")
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

# Bounded reprompts when the model's reply won't parse as JSON: the gateway's Anthropic route doesn't
# reliably honour json_object mode, so the initial call occasionally returns prose or a fenced/partial
# object. One strict-JSON reprompt clears almost all of these; the rest degrade to a "partial" sync.
MAX_JSON_COMPLETION_ATTEMPTS = 2


class EnrichmentResponseNotJSONError(ValueError):
    """The model's reply couldn't be parsed as a JSON object, even after a strict-JSON reprompt.

    A dedicated type (subclassing ``ValueError`` for backwards compatibility) so the caller can treat
    this expected, self-healing case — a later idempotent sync re-enriches the skipped columns —
    differently from genuine failures: it degrades to a "partial" status without opening an
    error-tracking issue, while other exceptions (gateway misconfig, context-window overflow) are still
    reported.
    """


def collapse_untrusted(text: str) -> str:
    """Collapse whitespace (incl. control chars) in source-derived identifiers/comments.

    Column names, data types, foreign-key identifiers, and native comments come from a source outside
    our trust boundary. Collapsing runs of whitespace onto a single line stops a crafted value from
    breaking out into a fake heading or list item in the prompt; the prompt's framing already tells
    the model to treat these as untrusted data rather than instructions.
    """
    return _WHITESPACE_RE.sub(" ", text).strip()


def extract_json_object(content: str) -> dict[str, Any] | None:
    """Parse the model's JSON reply, tolerating markdown fences or surrounding prose.

    `response_format={"type": "json_object"}` isn't reliably honoured through the gateway's Anthropic
    route, so the reply can arrive fenced (```json … ```) or with leading text — a bare `json.loads`
    then dies on the first non-`{` character. Try the whole string, then a fenced block, then the
    outermost `{…}` span. Returns the dict, or None if nothing parses to a JSON object.
    """
    text = content.strip()
    candidates = [text]
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        candidates.append(fence.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def estimate_prompt_tokens(text: str) -> int:
    """Estimate the token count of an assembled prompt, for keeping it under the model's input window.

    Uses tiktoken's o200k encoding as a model-agnostic proxy — the enrichment model is Anthropic, but a
    close, slightly conservative estimate is all a safety bound needs. Falls back to a dense
    chars-per-token heuristic if the encoding can't be loaded (tiktoken can hit transient blob issues on
    first use), so bounding never crashes enrichment; overestimating tokens only trims more, which is the
    safe direction.
    """
    try:
        return len(get_tiktoken_encoding_for_model(LLM_TOKEN_COUNT_PROXY_MODEL).encode(text))
    except Exception:
        # ~2 chars/token is dense for mixed structured/non-English content; this overestimates for
        # English, and overestimating tokens can only make bounding trim more aggressively.
        return len(text) // 2


def enrichment_enabled(team: Team, flag_key: str) -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                flag_key,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        capture_exception(e)
        return False


def capture_enrichment_event(team: Team, event: str, properties: dict[str, Any]) -> None:
    """Best-effort product-analytics capture, attributed to the team's org/project groups.

    Telemetry must never break enrichment, so all failures are swallowed (and reported to Sentry).
    """
    try:
        posthoganalytics.capture(
            distinct_id=str(team.uuid),
            event=event,
            properties={**properties, "team_id": team.id},
            groups={"organization": str(team.organization_id), "project": str(team.id)},
        )
    except Exception as e:
        capture_exception(e)


def get_team_business_context(team: Team) -> str:
    """The team's core memory (what the company does, their terminology), if any."""
    # Imported lazily — posthog_ai pulls in the assistant stack we don't want on this module's import path.
    from products.posthog_ai.backend.models.assistant import CoreMemory  # noqa: PLC0415

    core_memory = CoreMemory.objects.filter(team=team).first()
    return (core_memory.text or "").strip() if core_memory else ""


def generate_json_completion(
    *,
    product: Product,
    team_id: int,
    prompt: str,
    model: str = DEFAULT_ENRICHMENT_MODEL,
    temperature: float = 0.2,
    client: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Call the LLM for a JSON reply. Returns `(parsed_payload, usage)` — usage carries model + tokens.

    `client` lets a caller inject an already-resolved gateway client (the warehouse path does this so
    its existing test seam keeps working); when omitted we resolve one for `product`/`team_id`.

    `response_format={"type": "json_object"}` isn't reliably honoured through the gateway's Anthropic
    route, so an initial reply can arrive as prose or a partial object. We reprompt for strict JSON up to
    `MAX_JSON_COMPLETION_ATTEMPTS` before giving up with `EnrichmentResponseNotJSONError` — the caller
    treats that as an expected, self-healing "partial" rather than an error-tracking issue.
    """
    if client is None:
        client = get_llm_client(product=product, team_id=team_id)

    messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]
    for _attempt in range(MAX_JSON_COMPLETION_ATTEMPTS):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
            user=f"team-{team_id}",
        )
        usage_obj = getattr(response, "usage", None)
        usage: dict[str, Any] = {
            "model": model,
            "prompt_tokens": getattr(usage_obj, "prompt_tokens", None),
            "completion_tokens": getattr(usage_obj, "completion_tokens", None),
            "total_tokens": getattr(usage_obj, "total_tokens", None),
        }
        content = response.choices[0].message.content or ""
        parsed = extract_json_object(content)
        if parsed is not None:
            return parsed, usage
        # Feed the model its own off-format reply back and ask, firmly, for JSON only. Almost all of the
        # rare non-JSON replies clear on this single reprompt.
        messages = [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": "Your previous reply was not valid JSON. Respond with ONLY the JSON object "
                "requested — no prose, no markdown code fences, no comments.",
            },
        ]

    # Surface as an LLM failure (caught by the caller → "partial") rather than silently persisting
    # nothing. The dedicated type lets the caller skip error-tracking for this self-healing case.
    raise EnrichmentResponseNotJSONError("model response was not valid JSON")


def bound_prompt_over_columns(
    builder: Callable[[list[dict[str, Any]], list[str]], str],
    columns: list[dict[str, Any]],
    columns_needing_description: list[str],
    max_prompt_tokens: int = MAX_PROMPT_TOKENS,
) -> str:
    """Build a prompt via `builder`, dropping tail columns until it fits the model's token window.

    `builder(shown_columns, columns_needing_description)` assembles the surface-specific prompt from a
    subset of columns; anything else it depends on (foreign keys, business context, …) is closed over
    by the caller and re-derived from `shown_columns` on each call so the prompt never references a
    column it no longer lists. If the assembled prompt is still too long — a pathologically wide table,
    say — columns are dropped from the tail until it fits. Bounding is by estimated tokens, not chars,
    because the prompt's structured/multilingual content tokenizes far denser than English prose.
    Skipped columns keep their place in the idempotency snapshot, so a later pass enriches them.
    """
    shown_columns = columns
    needing = columns_needing_description
    while True:
        prompt = builder(shown_columns, needing)
        if estimate_prompt_tokens(prompt) <= max_prompt_tokens or len(shown_columns) <= 1:
            return prompt
        # Drop ~10% of the tail columns and re-measure. Prune the ask list to the surviving columns too.
        cut = max(1, len(shown_columns) // 10)
        shown_columns = shown_columns[:-cut]
        kept_names = {column["name"] for column in shown_columns}
        needing = [name for name in needing if name in kept_names]


def upsert_column_annotation(
    *,
    model: Any,
    team_id: int,
    owner: dict[str, Any],
    column_name: str,
    description: str,
    source: str,
    ai_model: str | None,
) -> None:
    """Persist one annotation for a column the caller's snapshot found unannotated.

    `owner` is the model-specific owning relation ({"table": table} for warehouse, {"saved_query": sq}
    for data-modeling views). Uses get_or_create plus a guarded update rather than update_or_create so a
    user edit that lands in the race window between the caller's snapshot and this write is never
    clobbered: if a user-edited row now exists for this (owner, column), we leave it untouched, honouring
    the is_user_edited guarantee at write time rather than only at snapshot time.
    """
    annotation, created = model.objects.for_team(team_id).get_or_create(
        **owner,
        column_name=column_name,
        defaults={
            "team_id": team_id,
            "description": description,
            "description_source": source,
            "ai_model": ai_model,
        },
    )
    if created or annotation.is_user_edited:
        return
    # Guarded update: only write when the row is still not user-edited in the DB, so an edit that lands in
    # the race window between the get_or_create read and this write is honoured rather than clobbered.
    # update() bypasses auto_now, so updated_at is set explicitly.
    model.objects.for_team(team_id).filter(id=annotation.id, is_user_edited=False).update(
        description=description,
        description_source=source,
        ai_model=ai_model,
        updated_at=timezone.now(),
    )
