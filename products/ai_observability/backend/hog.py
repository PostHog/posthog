from typing import Any, Literal

from posthog.cdp.validation import compile_hog

AIObservabilityHogType = Literal["destination", "tagger"]


def compile_ai_observability_hog(source: str, hog_type: AIObservabilityHogType) -> list[Any]:
    return compile_hog(source, hog_type, null_safe_comparisons=True)
