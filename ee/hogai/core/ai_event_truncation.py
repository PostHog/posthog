"""Truncate oversized AI analytics events before the PostHog SDK queues them.

The vendored ``posthoganalytics`` Consumer drops any single event larger than 900 KiB
client-side (``consumer.py`` ``MAX_MSG_SIZE``), before it ever reaches capture. Max AI's
``$ai_trace``/``$ai_span``/``$ai_generation`` events carry full LangGraph state and model
context blobs that routinely exceed that, so the whole event — including the data billing
reads — is silently lost.

``AIEventTruncator`` is wired as the SDK's public ``before_send`` hook (runs on the built
event dict before the size check). It shrinks the heavy blobs while preserving the fields the
usage report reads off ``$ai_trace.$ai_output_state`` — each message's ``type`` and its
``tool_calls`` (``name`` + ``args.kind``) — so billing stays correct. Token-count properties
live as separate top-level keys and are never touched.
"""

import json
from copy import deepcopy
from typing import Any

import structlog
from prometheus_client import Counter

logger = structlog.get_logger(__name__)

# Default budgets (tunable per AIEventTruncator instance). Each truncated property is capped at
# PER_BLOB_BYTE_BUDGET — well under the SDK's 900 KiB per-event drop. A single event carries up to
# two of the truncated blobs, so two full per-blob budgets would still exceed the drop;
# COMBINED_EVENT_CEILING trims the present blobs so their combined size clears it with margin for
# the small non-blob properties.
PER_BLOB_BYTE_BUDGET = 700 * 1024
COMBINED_EVENT_CEILING = 850 * 1024
# Tier 1 caps individual string leaves (message content, tool/SQL output) to this many chars.
PER_STRING_CAP = 10_000
# Tier 3 never front-trims the messages list below this many entries.
MIN_TAIL_MESSAGES = 1
TRUNCATION_MARKER = "...truncated"

TRUNCATABLE_AI_EVENTS = frozenset({"$ai_trace", "$ai_span", "$ai_generation"})
# State blobs on $ai_trace/$ai_span, and model input/output on $ai_generation.
TRUNCATABLE_PROPS = ("$ai_input_state", "$ai_output_state", "$ai_input", "$ai_output_choices")
# Set on the event when anything was truncated, so it's queryable in PostHog.
TRUNCATED_FLAG_PROP = "$ai_event_truncated"
# Short structural fields kept when a message is reduced to its billing-critical shape.
_KEPT_MESSAGE_FIELDS = ("type", "role", "id", "name", "tool_call_id")

AI_EVENT_TRUNCATED_COUNTER = Counter(
    "posthog_ai_event_truncated_total",
    "AI event blobs truncated before capture to stay under the SDK per-event size limit",
    ["event", "property", "tier"],  # $ai_trace|$ai_span|$ai_generation ; property name ; leaf|strip|trim|hard
)


def byte_size(obj: Any) -> int:
    """Serialized UTF-8 byte size, mirroring how the SDK Consumer measures an event."""
    try:
        return len(json.dumps(obj, default=str).encode())
    except (TypeError, ValueError):
        # Unserializable here would also fail in the SDK; treat as oversized so it gets truncated.
        return COMBINED_EVENT_CEILING * 2


class AIEventTruncator:
    """Billing-safe truncation of oversized AI analytics events for the SDK ``before_send`` hook.

    Instances are callable so they can be passed directly as ``before_send``. Budgets are
    configurable per instance; the defaults match the module-level constants.
    """

    def __init__(
        self,
        *,
        per_blob_byte_budget: int = PER_BLOB_BYTE_BUDGET,
        combined_event_ceiling: int = COMBINED_EVENT_CEILING,
        per_string_cap: int = PER_STRING_CAP,
        min_tail_messages: int = MIN_TAIL_MESSAGES,
    ):
        self.per_blob_byte_budget = per_blob_byte_budget
        self.combined_event_ceiling = combined_event_ceiling
        self.per_string_cap = per_string_cap
        self.min_tail_messages = min_tail_messages

    def __call__(self, msg: Any) -> dict[str, Any]:
        return self.truncate_event(msg)

    def truncate_event(self, msg: Any) -> dict[str, Any]:
        """``before_send`` hook: truncate oversized blobs on AI events so they clear the SDK's
        per-event size drop. No-op for non-AI events and under-budget blobs. Never raises."""
        try:
            if not isinstance(msg, dict):
                return msg
            event = msg.get("event")
            if event not in TRUNCATABLE_AI_EVENTS:
                return msg
            properties = msg.get("properties")
            if not isinstance(properties, dict):
                return msg

            changed_tiers: dict[str, str] = {}
            for prop in TRUNCATABLE_PROPS:
                if properties.get(prop) is None:
                    continue
                new_value, tier = self.truncate_blob(properties[prop])
                if tier is not None:
                    properties[prop] = new_value
                    changed_tiers[prop] = tier

            present_props = [prop for prop in TRUNCATABLE_PROPS if properties.get(prop) is not None]
            if present_props:
                self._enforce_combined_ceiling(properties, present_props, changed_tiers)

            for prop, tier in changed_tiers.items():
                AI_EVENT_TRUNCATED_COUNTER.labels(event=event, property=prop, tier=tier).inc()
            if changed_tiers:
                properties[TRUNCATED_FLAG_PROP] = True
            return msg
        except Exception:
            # Degrade gracefully — the SDK also try/excepts before_send, but never let the hook break capture.
            logger.exception("truncate_ai_event_failed")
            return msg

    def truncate_blob(self, value: Any, *, byte_budget: int | None = None) -> tuple[Any, str | None]:
        """Truncate a single blob to ``byte_budget`` (defaults to the per-blob budget), billing-safe.
        Never mutates ``value``.

        Returns ``(value_or_truncated_copy, tier)`` where ``tier`` is ``None`` (no-op) or one of
        ``"leaf"``/``"strip"``/``"trim"``/``"hard"`` for metrics. Handles dicts with a ``messages``
        list, bare lists of messages (``$ai_input``/``$ai_output_choices``), and other shapes.
        """
        budget = self.per_blob_byte_budget if byte_budget is None else byte_budget

        if byte_size(value) <= budget:
            return value, None

        # Tier 1 — cap long string leaves, keeping all structure.
        work = self._cap_leaf_strings(deepcopy(value))
        if byte_size(work) <= budget:
            return work, "leaf"

        # Tier 2/3 — reduce messages to billing-critical fields, then front-trim if still too large.
        if isinstance(work, list):
            stripped = [self._strip_message_to_billing(message) for message in work]
            if byte_size(stripped) <= budget:
                return stripped, "strip"
            return self._front_trim_messages(stripped, budget), "trim"

        holder, key = self._find_messages(work)
        if holder is not None and key is not None:
            stripped = [self._strip_message_to_billing(message) for message in holder[key]]
            # Re-emit under top-level "messages" (where billing reads it), discarding other state keys.
            if byte_size({"messages": stripped}) <= budget:
                return {"messages": stripped}, "strip"
            return {"messages": self._front_trim_messages(stripped, budget)}, "trim"

        # Fallback — no recognizable messages; guarantee the bound.
        return self._hard_truncate(value, budget), "hard"

    def _enforce_combined_ceiling(
        self,
        properties: dict[str, Any],
        present_props: list[str],
        changed_tiers: dict[str, str],
    ) -> None:
        """Trim the largest present blob so all present blobs together clear the per-event drop."""
        sizes = {prop: byte_size(properties[prop]) for prop in present_props}
        if sum(sizes.values()) <= self.combined_event_ceiling:
            return
        largest = max(present_props, key=lambda prop: sizes[prop])
        others = sum(size for prop, size in sizes.items() if prop != largest)
        new_value, tier = self.truncate_blob(
            properties[largest], byte_budget=max(0, self.combined_event_ceiling - others)
        )
        properties[largest] = new_value
        if tier is not None:
            changed_tiers[largest] = tier

    def _cap_leaf_strings(self, obj: Any) -> Any:
        """Recursively cap long string leaves in-place. Preserves all keys and structure, so short
        billing fields (``type``, ``tool_calls[].name``, ``args.kind``) survive untouched."""
        if isinstance(obj, str):
            return obj[: self.per_string_cap] + TRUNCATION_MARKER if len(obj) > self.per_string_cap else obj
        if isinstance(obj, dict):
            for key, value in obj.items():
                obj[key] = self._cap_leaf_strings(value)
            return obj
        if isinstance(obj, list):
            for index, value in enumerate(obj):
                obj[index] = self._cap_leaf_strings(value)
            return obj
        return obj

    def _front_trim_messages(self, messages: list[Any], byte_budget: int) -> list[Any]:
        """Drop messages from the FRONT (keep the tail) until under budget. Billing reads only the
        current turn — the messages after the last human message — which lives at the tail."""
        trimmed = messages
        while len(trimmed) > self.min_tail_messages and byte_size(trimmed) > byte_budget:
            trimmed = trimmed[1:]
        # Even the minimum tail can blow the budget (e.g. one giant message). Guarantee the bound
        # with a hard fallback rather than letting an oversized blob through to the SDK drop.
        if byte_size(trimmed) > byte_budget:
            return [self._hard_truncate(trimmed, byte_budget)]
        return trimmed

    @staticmethod
    def _strip_tool_call(tool_call: Any) -> Any:
        """Reduce a tool call to what billing reads: ``name`` (+ ``id``) and, only for ``search``,
        ``args.kind`` (the docs-search exclusion). Other args are dropped — billing never reads them."""
        if not isinstance(tool_call, dict):
            return tool_call
        reduced: dict[str, Any] = {}
        name = tool_call.get("name")
        if name is not None:
            reduced["name"] = name
        if "id" in tool_call:
            reduced["id"] = tool_call["id"]
        if name == "search":
            args = tool_call.get("args")
            if isinstance(args, dict) and "kind" in args:
                reduced["args"] = {"kind": args["kind"]}
        return reduced

    @classmethod
    def _strip_message_to_billing(cls, message: Any) -> Any:
        """Reduce a message to short, billing-critical fields, dropping heavy ``content``."""
        if not isinstance(message, dict):
            return message
        reduced: dict[str, Any] = {field: message[field] for field in _KEPT_MESSAGE_FIELDS if field in message}
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            reduced["tool_calls"] = [cls._strip_tool_call(tc) for tc in tool_calls]
        return reduced

    @staticmethod
    def _find_messages(obj: Any) -> tuple[dict[str, Any] | None, str | None]:
        """Locate a ``messages`` list: top-level first (the real ``$ai_output_state`` shape), then one
        nested level. Returns the holding dict and key, or ``(None, None)``."""
        if isinstance(obj, dict):
            if isinstance(obj.get("messages"), list):
                return obj, "messages"
            for value in obj.values():
                if isinstance(value, dict) and isinstance(value.get("messages"), list):
                    return value, "messages"
        return None, None

    @staticmethod
    def _hard_truncate(value: Any, byte_budget: int) -> dict[str, Any]:
        """Last-resort bound for shapes with no recognizable messages list."""
        preview_chars = max(0, byte_budget // 2)
        return {TRUNCATED_FLAG_PROP: True, "preview": json.dumps(value, default=str)[:preview_chars]}


# Default instance used as the SDK before_send hook (see runner.init_handler).
ai_event_truncator = AIEventTruncator()
