from __future__ import annotations

from posthog.models.hog_functions.hog_function import HogFunctionType


def humanize_hog_function_type(hog_type: str | None) -> str:
    """Return a human friendly label for a Hog function type."""

    if not hog_type:
        return "hog function"

    if hog_type == HogFunctionType.SOURCE_WEBHOOK:
        return "source"

    return hog_type.replace("_", " ")
