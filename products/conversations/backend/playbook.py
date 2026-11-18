"""Support-reply playbook layers: repo defaults, optional PostHog overlay, team custom.

Compose is Django-free so the draft activity and settings API share one source of truth
without pulling Temporal or ORM into either caller.
"""

from __future__ import annotations

import re
import hashlib
from typing import Any

from posthog.dataclasses import frozen

DOCS_SOURCE_POSTHOG = "posthog"
DOCS_SEARCH_TOOL_NAME = "docs-search"
MAX_CUSTOM_INSTRUCTIONS_CHARS = 8000

DEFAULT_SUPPORT_REPLY_INSTRUCTIONS_VERSION = 1
POSTHOG_SUPPORT_REPLY_INSTRUCTIONS_VERSION = 1

LAYER_DEFAULT = "default"
LAYER_POSTHOG = "posthog"
LAYER_CUSTOM = "custom"

WARNING_CUSTOM_OVERSIZED = "custom_instructions_oversized"
WARNING_CUSTOM_INVALID = "custom_instructions_invalid"

DEFAULT_SUPPORT_REPLY_INSTRUCTIONS = """\
You are drafting a support reply for this team's product. Do not assume the product is PostHog.

Tone:
- Be direct, friendly, and concise. Lead with the answer.
- Do not promise refunds, credits, or policy exceptions the team policy does not allow.

Answer-first drafting:
- Open with the resolution or the next step. Put background after.
- Keep the customer-facing reply short. Put investigation detail in investigation_summary.

Citation discipline:
- Every factual claim needs a source: a business-knowledge chunk_id or a documentation URL this team's knowledge returned.
- If you cannot cite it, do not claim it.

When to clarify:
- Ask only when a missing customer fact blocks any useful answer.
- One short question that states why you need the fact.

Investigation planning:
- List what you need to know and which tool on this run answers each question, then run that plan before drafting.
- Prefer this team's business knowledge over guessing.
- When analytics or project-data tools are listed for this run, use them to verify what the customer reports. Summarize findings. Do not paste raw PII.

Business knowledge:
- Learned chunks labeled [learned from support] are how this team resolved a past ticket. Treat them as team practice, not as product documentation.
- TEAM POLICY overrides generic documentation on any conflict.
"""

POSTHOG_SUPPORT_REPLY_INSTRUCTIONS = """\
This team supports PostHog.

Use official PostHog documentation via docs-search for product features, billing, setup, SDKs, and APIs.

When the ticket matches a bundled skill, read and follow that skill:
- diagnosing-missing-recordings: session replay is missing or blank
- diagnosing-sdk-health: events or identify calls are not arriving
- investigating-error-issue: an exception or error-tracking issue
- diagnosing-stacktrace-symbolication: unsymbolicated or wrong stack traces

Do not invent PostHog product behavior that docs-search and those skills do not support.
"""


@frozen
class PlaybookComposition:
    text: str
    inherited_text: str
    custom_text: str | None
    layers: tuple[str, ...]
    default_version: int
    posthog_overlay_version: int | None
    content_hash: str
    warnings: tuple[str, ...]
    docs_source: str | None
    mcp_exclude_tools: tuple[str, ...]

    def provenance(self) -> dict[str, Any]:
        return {
            "layers": list(self.layers),
            "default_version": self.default_version,
            "posthog_overlay_version": self.posthog_overlay_version,
            "content_hash": self.content_hash,
            "warnings": list(self.warnings),
        }


def is_posthog_docs_source(docs_source: str | None) -> bool:
    return docs_source == DOCS_SOURCE_POSTHOG


def mcp_exclude_tools_for_docs_source(docs_source: str | None) -> tuple[str, ...]:
    if is_posthog_docs_source(docs_source):
        return ()
    return (DOCS_SEARCH_TOOL_NAME,)


_LAYER_TAG_RE = re.compile(r"</?playbook_layer\b[^>]*>", re.IGNORECASE)


def _layer_block(name: str, body: str, version: int | None = None) -> str:
    version_attr = f' version="{version}"' if version is not None else ""
    return f'<playbook_layer name="{name}"{version_attr}>\n{body.strip()}\n</playbook_layer>'


def _sanitize_custom_layer_body(body: str) -> str:
    # Layer tags are delimiters. Strip them from team text so custom instructions cannot close a layer.
    return _LAYER_TAG_RE.sub("", body).strip()


def _as_custom_addendum(custom: str, inherited_text: str) -> str | None:
    # Custom is an addendum. If the saved text repeats the inherited playbook, keep only
    # what follows so a full-text save cannot freeze a snapshot over later default edits.
    if custom == inherited_text:
        return None
    if custom.startswith(inherited_text):
        rest = custom[len(inherited_text) :].strip()
        return rest or None
    return custom


def _normalize_custom_instructions(custom_instructions: object) -> tuple[str | None, tuple[str, ...]]:
    if custom_instructions is None:
        return None, ()
    if not isinstance(custom_instructions, str):
        return None, (WARNING_CUSTOM_INVALID,)
    stripped = custom_instructions.strip()
    if not stripped:
        return None, ()
    sanitized = _sanitize_custom_layer_body(stripped)
    if not sanitized:
        return None, ()
    return sanitized, ()


def compose_support_playbook(
    *,
    docs_source: str | None = None,
    custom_instructions: object = None,
) -> PlaybookComposition:
    """Compose the effective playbook: generic default, optional PostHog overlay, then team custom.

    Absence of custom instructions means inherit. Oversized or invalid custom falls back to
    repo layers and records a warning so a bad settings row cannot stop ticket processing.
    """
    posthog = is_posthog_docs_source(docs_source)
    custom, warnings = _normalize_custom_instructions(custom_instructions)

    inherited_parts = [DEFAULT_SUPPORT_REPLY_INSTRUCTIONS.strip()]
    if posthog:
        inherited_parts.append(POSTHOG_SUPPORT_REPLY_INSTRUCTIONS.strip())
    inherited_text = "\n\n".join(inherited_parts)
    if custom is not None:
        custom = _as_custom_addendum(custom, inherited_text)
        # Cap the addendum, not a pasted copy of the inherited playbook.
        if custom is not None and len(custom) > MAX_CUSTOM_INSTRUCTIONS_CHARS:
            custom = None
            warnings = (WARNING_CUSTOM_OVERSIZED,)

    layers: list[str] = [LAYER_DEFAULT]
    delimited = [
        _layer_block(LAYER_DEFAULT, DEFAULT_SUPPORT_REPLY_INSTRUCTIONS, DEFAULT_SUPPORT_REPLY_INSTRUCTIONS_VERSION)
    ]
    overlay_version: int | None = None
    if posthog:
        layers.append(LAYER_POSTHOG)
        overlay_version = POSTHOG_SUPPORT_REPLY_INSTRUCTIONS_VERSION
        delimited.append(
            _layer_block(
                LAYER_POSTHOG,
                POSTHOG_SUPPORT_REPLY_INSTRUCTIONS,
                POSTHOG_SUPPORT_REPLY_INSTRUCTIONS_VERSION,
            )
        )
    if custom is not None:
        layers.append(LAYER_CUSTOM)
        delimited.append(_layer_block(LAYER_CUSTOM, custom))

    text = "\n\n".join(delimited)
    content_hash = hashlib.sha256(text.encode()).hexdigest()
    return PlaybookComposition(
        text=text,
        inherited_text=inherited_text,
        custom_text=custom,
        layers=tuple(layers),
        default_version=DEFAULT_SUPPORT_REPLY_INSTRUCTIONS_VERSION,
        posthog_overlay_version=overlay_version,
        content_hash=content_hash,
        warnings=warnings,
        docs_source=DOCS_SOURCE_POSTHOG if posthog else None,
        mcp_exclude_tools=mcp_exclude_tools_for_docs_source(docs_source),
    )
