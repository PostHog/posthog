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
from collections.abc import Callable, Iterable
from math import ceil
from typing import Any

from django.utils import timezone

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.llm.gateway_client import (
    Product,
    build_anthropic_client,
    get_llm_client,
    resolve_ai_gateway_config,
    team_distinct_id,
)
from posthog.models import Team

DEFAULT_ENRICHMENT_MODEL = "claude-haiku-4-5"
# Ceiling for one reply, not the value sent: the reply echoes each column name as a JSON key, so a
# table's need scales with its name lengths. `bound_prompt_over_columns` sizes and bounds the ask.
MAX_OUTPUT_TOKENS = 16384
# Floor for the sized ceiling, so a narrow table still has room to answer.
MIN_OUTPUT_TOKENS = 1024
# What one `"name": "sentence"` pair costs beyond the name itself: the quotes, colon, comma and
# newline, then a sentence of description.
_JSON_PAIR_OVERHEAD_CHARS = 8
_DESCRIPTION_BUDGET_CHARS = 240
# Deliberately below the ~3.5 chars/token English average: under-reserving truncates the reply, while
# over-reserving only leaves headroom unused.
_CHARS_PER_OUTPUT_TOKEN = 3.0
# Keep the prompt and response bounded — wide tables shouldn't blow up the context or the cost.
MAX_COLUMNS_PER_TABLE = 200
# Calls one run may spend finishing a table one reply cannot hold. A caller whose completion marker
# covers the whole object has to finish here, or a column it never asked about is latched as done.
MAX_ENRICHMENT_BATCHES = 4
# Wall clock after which a run starts no further batches; the first call always runs, so batching
# cannot breach a deadline one call would have met. Sized inside the enrichment activity's timeout
# but not derived from it: across packages a silent drift would surface as a timeout, not a shortfall.
ENRICHMENT_BATCH_BUDGET_SECONDS = 300.0
# The team's core memory is free-form and unbounded; a large dump alone can push the prompt past the
# model's 200k-token context window. Cap it — a concise company summary is all the enrichment needs.
MAX_BUSINESS_CONTEXT_CHARS = 20_000
# Last-resort ceiling on the whole assembled prompt. Stays well under the 200k-token window (English
# is ~3-4 chars/token, so this is ~100-130k tokens) to leave room for the response. If the prompt
# still exceeds it after capping the business context, we drop columns from the tail until it fits;
# enrichment is idempotent, so a later pass fills in whatever this one skips.
MAX_PROMPT_CHARS = 400_000

_WHITESPACE_RE = re.compile(r"\s+")
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


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

    Callers that cannot set a response-format parameter, the Messages leg among them, ask for JSON in
    the prompt, so the reply can arrive fenced (```json … ```) or with leading text and a bare
    `json.loads` dies on the first non-`{` character. Try the whole string, then a fenced block, then
    the outermost `{…}` span. Returns the dict, or None if nothing parses to a JSON object.
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

    Telemetry must never break enrichment, so all failures are swallowed (and captured for error tracking).
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


class TruncatedCompletionError(ValueError):
    """The model hit its output ceiling, so the reply is cut off rather than malformed.

    A `ValueError` so the callers' existing `except Exception` handlers keep reporting "partial",
    but a distinct type and message so a too-small ceiling is separable from a bad reply.
    """


@frozen
class _Completion:
    """One model reply, normalised across the two request shapes."""

    text: str
    usage: dict[str, Any]
    truncated: bool
    # The ceiling this leg sent, for the truncation message. None when the provider applied its own.
    max_output_tokens: int | None = None


class _MessagesClient:
    """Anthropic Messages, the only shape the Go ai-gateway plans Claude models under."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def complete(
        self, *, model: str, prompt: str, temperature: float, team_id: int, max_output_tokens: int = MAX_OUTPUT_TOKENS
    ) -> _Completion:
        response = self._client.messages.create(
            model=model,
            max_tokens=max_output_tokens,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            metadata={"user_id": team_distinct_id(team_id)},
        )
        usage_obj = getattr(response, "usage", None)
        prompt_tokens = getattr(usage_obj, "input_tokens", None)
        completion_tokens = getattr(usage_obj, "output_tokens", None)
        return _Completion(
            text=_messages_text(response),
            usage=_usage(model, prompt_tokens, completion_tokens),
            truncated=getattr(response, "stop_reason", None) == "max_tokens",
            max_output_tokens=max_output_tokens,
        )


class _ChatClient:
    """OpenAI Chat Completions, the shape the Python gateway has always served this product."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def complete(
        self, *, model: str, prompt: str, temperature: float, team_id: int, max_output_tokens: int = MAX_OUTPUT_TOKENS
    ) -> _Completion:
        # No max_tokens: this leg lets the provider apply its own ceiling, and the bounded ask list
        # already keeps the reply to one response.
        response = self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            response_format={"type": "json_object"},
            user=team_distinct_id(team_id),
        )
        choice = response.choices[0]
        usage_obj = getattr(response, "usage", None)
        return _Completion(
            text=choice.message.content or "",
            usage=_usage(
                model,
                getattr(usage_obj, "prompt_tokens", None),
                getattr(usage_obj, "completion_tokens", None),
            ),
            truncated=getattr(choice, "finish_reason", None) == "length",
        )


def _usage(model: str, prompt_tokens: int | None, completion_tokens: int | None) -> dict[str, Any]:
    """Token counts under the OpenAI key names the enrichment analytics events already carry."""
    return {
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": None
        if prompt_tokens is None or completion_tokens is None
        else prompt_tokens + completion_tokens,
    }


def _messages_text(response: Any) -> str:
    """Concatenate the text blocks of a Messages reply; other block types are ignored."""
    blocks = getattr(response, "content", None) or []
    return "".join(getattr(block, "text", None) or "" for block in blocks if getattr(block, "type", None) == "text")


def build_enrichment_client(product: Product, team_id: int) -> _MessagesClient | _ChatClient:
    """Client for one enrichment call, on whichever shape the resolved gateway serves.

    The Go ai-gateway plans Claude models only under Anthropic's native Messages shape, so the cutover
    sends Messages there. The Python gateway keeps receiving Chat Completions, which is what this
    product has always sent it, so clearing `AI_GATEWAY_URL` restores the previous wire behaviour rather
    than falling back onto a route the product has never exercised.
    """
    if resolve_ai_gateway_config():
        # The Messages `metadata.user_id` goes upstream to the provider; capture identity comes from
        # the X-PostHog-Distinct-Id header this sets, so without it the team is not attributed.
        return _MessagesClient(
            build_anthropic_client(product, ai_product=product, team_id=team_id, distinct_id=team_distinct_id(team_id))
        )
    return _ChatClient(get_llm_client(product=product, team_id=team_id))


def generate_json_completion(
    *,
    product: Product,
    team_id: int,
    prompt: str,
    model: str = DEFAULT_ENRICHMENT_MODEL,
    temperature: float = 0.2,
    client: "_MessagesClient | _ChatClient | None" = None,
    max_output_tokens: int = MAX_OUTPUT_TOKENS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Call the LLM for a JSON reply. Returns `(parsed_payload, usage)` — usage carries model + tokens.

    `client` lets a caller inject an already-resolved enrichment client (the warehouse path does this
    so its existing test seam keeps working); when omitted we resolve one for `product`/`team_id`.
    Raises `TruncatedCompletionError` when the reply was cut off by the output ceiling.
    """
    if client is None:
        client = build_enrichment_client(product, team_id)
    completion = client.complete(
        model=model, prompt=prompt, temperature=temperature, team_id=team_id, max_output_tokens=max_output_tokens
    )
    if completion.truncated:
        # Terminal even when the fragment parses: the view consumer stores its enrichment hash on
        # any non-exception return, so a partial column set latches and no later run retries.
        ceiling = f"{completion.max_output_tokens}-token" if completion.max_output_tokens else "provider-default"
        raise TruncatedCompletionError(f"model response hit the {ceiling} output ceiling")
    parsed = extract_json_object(completion.text)
    if parsed is None:
        # Surface as an LLM failure (caught by the caller → "partial") rather than silently
        # persisting nothing, so the error stays visible in analytics.
        raise ValueError("model response was not valid JSON")
    return parsed, completion.usage


def projected_output_tokens(column_names: Iterable[str]) -> int:
    """Tokens the JSON reply needs to answer for `column_names`.

    Every column echoes its own name back as a key before its sentence, so a table of long names needs
    a far larger ceiling than a table of short ones with the same column count.
    """
    chars = sum(len(name) + _JSON_PAIR_OVERHEAD_CHARS + _DESCRIPTION_BUDGET_CHARS for name in column_names)
    # The enclosing braces, then the floor so a narrow table still has room to answer.
    return max(MIN_OUTPUT_TOKENS, ceil((chars + 2) / _CHARS_PER_OUTPUT_TOKEN))


@frozen
class BoundedPrompt:
    """A prompt sized to fit, plus the columns the bounding gave up to make it fit.

    `deferred` is what the caller still owes: it is empty on the ordinary path, and a caller whose
    idempotency marker covers the whole object must withhold that marker while it is not.
    """

    prompt: str
    max_output_tokens: int
    requested: list[str]
    deferred: list[str]


def bound_prompt_over_columns(
    builder: Callable[[list[dict[str, Any]], list[str]], str],
    columns: list[dict[str, Any]],
    columns_needing_description: list[str],
    max_prompt_chars: int = MAX_PROMPT_CHARS,
    max_output_tokens: int = MAX_OUTPUT_TOKENS,
) -> BoundedPrompt:
    """Build a prompt via `builder`, dropping tail columns until both the prompt and its reply fit.

    `builder(shown_columns, columns_needing_description)` assembles the surface-specific prompt from a
    subset of columns; anything else it depends on (foreign keys, business context, …) is closed over
    by the caller and re-derived from `shown_columns` on each call so the prompt never references a
    column it no longer lists. Two bounds drop tail columns: an assembled prompt too long for the
    context window, and an ask list whose reply could not fit under `max_output_tokens`. The second
    bound otherwise truncates the reply on every attempt, so the table never gets past a partial result.

    Dropping is deferral, not completion: the returned `deferred` names were never asked about, so a
    caller that records "enriched" for the whole object has to withhold that record until it is empty,
    or those columns are never described again. A caller whose idempotency is per column (an annotation
    row each) needs no such guard, because an undescribed column is simply still unannotated.
    """
    shown_columns = columns
    needing = columns_needing_description
    while True:
        prompt = builder(shown_columns, needing)
        needed_tokens = projected_output_tokens(needing)
        if (len(prompt) <= max_prompt_chars and needed_tokens <= max_output_tokens) or len(shown_columns) <= 1:
            asked = set(needing)
            return BoundedPrompt(
                prompt=prompt,
                max_output_tokens=min(needed_tokens, max_output_tokens),
                requested=list(needing),
                deferred=[name for name in columns_needing_description if name not in asked],
            )
        # Unasked columns go first: they cost prompt space without producing an answer, while dropping
        # an asked one defers real work. This ordering is what lets a caller batch; a blind tail slice
        # sheds the same names every pass, so the next batch asks for nothing.
        cut = max(1, len(shown_columns) // 10)
        asked = set(needing)
        tail = range(len(shown_columns) - 1, -1, -1)
        droppable = [i for i in tail if shown_columns[i]["name"] not in asked]
        droppable += [i for i in tail if shown_columns[i]["name"] in asked]
        dropped_indices = set(droppable[:cut])
        shown_columns = [column for i, column in enumerate(shown_columns) if i not in dropped_indices]
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
