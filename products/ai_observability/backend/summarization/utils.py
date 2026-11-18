"""Utility functions for summarization."""

from collections.abc import Collection
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from django.template import Context, Engine
from django.utils.dateparse import parse_datetime

from posthog.schema import DateRange

from products.access_control.backend.facade.property_access import restriction_fingerprint

if TYPE_CHECKING:
    from posthog.hogql.property_access_types import RestrictedProperty


def get_summarization_lookup_date_range(
    timestamp: object, *, date_from: str | None = None, date_to: str | None = None
) -> DateRange:
    date_range = DateRange(date_from=date_from, date_to=date_to)
    if not isinstance(timestamp, str) or (date_from and date_to):
        return date_range

    try:
        parsed_timestamp = parse_datetime(timestamp)
        if parsed_timestamp is not None:
            return DateRange(
                date_from=date_from or (parsed_timestamp - timedelta(days=1)).isoformat(),
                date_to=date_to or (parsed_timestamp + timedelta(days=1)).isoformat(),
            )
    except (ValueError, OverflowError):
        pass

    return date_range


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

    fingerprint = restriction_fingerprint(restricted_properties)
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
