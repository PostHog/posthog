"""Which OpenAI models may request the flex service tier."""

# OpenAI decides flex eligibility per model, and the pro tiers are excluded, so callers must
# check membership here rather than infer it from a model family prefix. This mirrors the flex
# table on https://developers.openai.com/api/docs/pricing?latest-pricing=flex (September 2026);
# a new model joins only after someone checks that page.
FLEX_CAPABLE_MODELS: frozenset[str] = frozenset(
    {
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "gpt-5.2",
        "gpt-5.1",
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
        "o3",
        "o4-mini",
    }
)
