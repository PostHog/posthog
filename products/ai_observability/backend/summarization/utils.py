"""Utility functions for summarization."""

import json
import hashlib
from collections.abc import Collection
from pathlib import Path
from typing import TYPE_CHECKING

from django.template import Context, Engine

if TYPE_CHECKING:
    from posthog.hogql.property_access_types import RestrictedProperty


def get_summary_cache_key(
    team_id: int,
    summarize_type: str,
    entity_id: str,
    mode: str = "minimal",
    model: str | None = None,
    *,
    restricted_properties: Collection["RestrictedProperty"] = (),
) -> str:
    model_key = model or "default"
    cache_key = f"llm_summary:{team_id}:{summarize_type}:{entity_id}:{mode}:{model_key}"
    if not restricted_properties:
        return cache_key

    restrictions = [
        (restriction.name, restriction.property_type, restriction.group_type_index)
        for restriction in sorted(
            restricted_properties,
            key=lambda restriction: (
                restriction.name,
                restriction.property_type,
                restriction.group_type_index if restriction.group_type_index is not None else -1,
            ),
        )
    ]
    fingerprint = hashlib.sha256(json.dumps(restrictions).encode()).hexdigest()
    return f"{cache_key}:properties:{fingerprint}"


def load_summarization_template(template_path: str, context: dict) -> str:
    """
    Load and render a Django template file.

    Args:
        template_path: Path to .djt template file relative to summarization module
        context: Dictionary of variables to pass to template

    Returns:
        Rendered template string (plain str, not SafeString)
    """
    templates_dir = Path(__file__).parent
    engine = Engine(dirs=[str(templates_dir)])
    template = engine.get_template(template_path)
    # Disable autoescape since we're generating LLM prompts, not HTML
    # Use [:] to convert SafeString to plain str (Gemini API doesn't handle SafeString properly)
    return template.render(Context(context, autoescape=False))[:]
