from typing import Literal

from posthog.dataclasses import frozen

PropertyScope = Literal["person", "event"]


@frozen
class DynamicPropertyVariant:
    """A longer form of a name, set in place of the base form under some configurations.

    The base form is then never set, so an agent that builds it reads an empty result and reports
    that the thing never happened. Naming the variant is what stops that silent wrong answer.
    """

    suffix_placeholder: str
    condition: str


@frozen
class DynamicPropertyPattern:
    """A property whose name ends in an id, so it never gets a `PropertyDefinition` row.

    Three surfaces need the same set, and they disagreed while each held its own copy: the
    taxonomy tool tells an agent how to build one of these names by hand, the HogQL taxonomy
    check must not call one unknown, and a property listing leaves them out. A name documented
    on one surface and missing from another reads to the caller as a broken taxonomy.
    """

    prefix: str
    placeholder: str
    scope: PropertyScope
    value_type: str
    description: str
    variants: tuple[DynamicPropertyVariant, ...] = ()

    @property
    def pattern(self) -> str:
        return f"{self.prefix}{{{self.placeholder}}}"

    def variant_pattern(self, variant: DynamicPropertyVariant) -> str:
        return f"{self.pattern}/{{{variant.suffix_placeholder}}}"


# Built by `_add_user_survey_interacted_filters` in `products/surveys/backend/api/survey.py`.
SURVEY_ITERATION_VARIANT = DynamicPropertyVariant(
    suffix_placeholder="iteration",
    condition="the survey repeats on a schedule",
)

DYNAMIC_PROPERTY_PATTERNS: tuple[DynamicPropertyPattern, ...] = (
    DynamicPropertyPattern(
        prefix="$feature/",
        placeholder="flag_key",
        scope="event",
        value_type="String",
        description="the feature flag value for a specific flag",
    ),
    DynamicPropertyPattern(
        prefix="$survey_dismissed/",
        placeholder="survey_id",
        scope="person",
        value_type="Boolean",
        description="survey dismiss tracking",
        variants=(SURVEY_ITERATION_VARIANT,),
    ),
    DynamicPropertyPattern(
        prefix="$survey_responded/",
        placeholder="survey_id",
        scope="person",
        value_type="Boolean",
        description="survey response tracking",
        variants=(SURVEY_ITERATION_VARIANT,),
    ),
    DynamicPropertyPattern(
        prefix="$feature_enrollment/",
        placeholder="flag_key",
        scope="person",
        value_type="Boolean",
        description="early access feature enrollment",
    ),
    DynamicPropertyPattern(
        prefix="$feature_interaction/",
        placeholder="feature_key",
        scope="person",
        value_type="Boolean",
        description="feature interaction tracking",
    ),
    DynamicPropertyPattern(
        prefix="$product_tour_shown/",
        placeholder="tour_id",
        scope="person",
        value_type="Boolean",
        description="product tour shown",
    ),
    DynamicPropertyPattern(
        prefix="$product_tour_dismissed/",
        placeholder="tour_id",
        scope="person",
        value_type="Boolean",
        description="product tour dismissed",
    ),
    DynamicPropertyPattern(
        prefix="$product_tour_completed/",
        placeholder="tour_id",
        scope="person",
        value_type="Boolean",
        description="product tour completed",
    ),
)

DYNAMIC_PROPERTY_PREFIXES: tuple[str, ...] = tuple(pattern.prefix for pattern in DYNAMIC_PROPERTY_PATTERNS)


def is_dynamic_property(name: str) -> bool:
    return name.startswith(DYNAMIC_PROPERTY_PREFIXES)


def dynamic_property_patterns(scope: PropertyScope) -> tuple[DynamicPropertyPattern, ...]:
    return tuple(pattern for pattern in DYNAMIC_PROPERTY_PATTERNS if pattern.scope == scope)


def format_dynamic_property_lines(patterns: tuple[DynamicPropertyPattern, ...]) -> str:
    """One bullet per pattern. A list that mixes scopes names the scope of each, because a reader
    cannot tell an event property from a person property by its name alone."""
    show_scope = len({pattern.scope for pattern in patterns}) > 1
    lines = []
    for pattern in patterns:
        scope = f"{pattern.scope} property, " if show_scope else ""
        line = f"- `{pattern.pattern}` ({scope}{pattern.value_type}): {pattern.description}"
        for variant in pattern.variants:
            line += f". When {variant.condition}, the name is `{pattern.variant_pattern(variant)}` instead"
        lines.append(line)
    return "\n".join(lines)
