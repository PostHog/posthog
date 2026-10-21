"""Validation and merging for HogQL query modifier settings."""

from rest_framework import exceptions

from posthog.schema import HogQLQueryModifiers

from products.web_analytics.backend.hogql_queries.custom_bot_definitions import (
    MAX_CUSTOM_BOT_DEFINITIONS,
    assert_patterns_compile as assert_custom_bot_patterns_compile,
    compiled_patterns as compiled_custom_bot_patterns,
    parse_rules as parse_custom_bot_rules,
    validate_rule as validate_custom_bot_rule,
    validate_rule_set as validate_custom_bot_rule_set,
)


def merge_modifiers(requested: dict | None, existing: object) -> dict | None:
    # Django admin can store a scalar or list here. Treat it as empty rather than raising.
    stored = existing if isinstance(existing, dict) else {}
    if requested is not None:
        return {**stored, **requested}
    # PostHog staff set useNewEventsSchema per project, so a client that clears its modifiers keeps it.
    if "useNewEventsSchema" in stored:
        return {"useNewEventsSchema": stored["useNewEventsSchema"]}
    return None


def validate_modifiers(value: dict | None) -> dict | None:
    if value is None:
        return value

    if not isinstance(value, dict):
        raise exceptions.ValidationError("Must provide a dictionary or None.")

    # The native JSON events table is an internal rollout switch that PostHog staff set per project in Django
    # admin. Dropping the key keeps a client from setting or clearing it, including a settings page that echoes
    # the whole modifiers dict back.
    value = {key: item for key, item in value.items() if key not in {"useNewEventsSchema", "useNewEventsCluster"}}

    if "bounceRateDurationSeconds" in value:
        bounce_rate = value["bounceRateDurationSeconds"]
        if bounce_rate is not None:
            if not isinstance(bounce_rate, (int, float)):
                raise exceptions.ValidationError({"bounceRateDurationSeconds": "Must be a number."})
            if bounce_rate < 1 or bounce_rate > 120:
                raise exceptions.ValidationError({"bounceRateDurationSeconds": "Must be between 1 and 120 seconds."})

    if "customBotDefinitions" in value and isinstance(value["customBotDefinitions"], list):
        # Cap before parsing, so an oversized list is rejected without instantiating a model
        # per entry.
        if len(value["customBotDefinitions"]) > MAX_CUSTOM_BOT_DEFINITIONS:
            raise exceptions.ValidationError(
                {"customBotDefinitions": f"You can define at most {MAX_CUSTOM_BOT_DEFINITIONS} bots."}
            )
        # Strict, so a malformed rule is rejected with a specific error rather than the
        # generic "Invalid modifier key.", and the stored list is normalized.
        try:
            parsed = parse_custom_bot_rules(value["customBotDefinitions"], strict=True)
        except ValueError as error:
            raise exceptions.ValidationError({"customBotDefinitions": str(error)})
        value = {**value, "customBotDefinitions": [rule.model_dump(exclude_none=True) for rule in parsed]}

    try:
        modifiers = HogQLQueryModifiers(**value)
    except Exception:
        raise exceptions.ValidationError(f"Invalid modifier key.")

    if "customBotDefinitions" in value:
        rules = modifiers.customBotDefinitions or []
        if len(rules) > MAX_CUSTOM_BOT_DEFINITIONS:
            raise exceptions.ValidationError(
                {"customBotDefinitions": f"You can define at most {MAX_CUSTOM_BOT_DEFINITIONS} bots."}
            )
        for rule in rules:
            # An unusable pattern would break every query that reads $virt_is_bot for this
            # project, so it is rejected here rather than dropped silently at query time.
            try:
                validate_custom_bot_rule(rule)
            except ValueError as error:
                # An empty name would render as an orphaned leading colon.
                message = f"{rule.name}: {error}" if rule.name else str(error)
                raise exceptions.ValidationError({"customBotDefinitions": message})
        try:
            validate_custom_bot_rule_set(rules)
            assert_custom_bot_patterns_compile(compiled_custom_bot_patterns(rules))
        except ValueError as error:
            raise exceptions.ValidationError({"customBotDefinitions": str(error)})

    return value
