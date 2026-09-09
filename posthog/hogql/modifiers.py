from typing import TYPE_CHECKING, Optional, overload

from posthog.cloud_utils import is_cloud
from posthog.schema_enums import (
    BounceRatePageViewMode,
    InCohortVia,
    InlineCohortCalculation,
    MaterializationMode,
    PersonsArgMaxVersion,
    PersonsOnEventsMode,
    PropertyGroupsMode,
    SessionsV2JoinMode,
    SessionTableVersion,
)

# This module loads at django.setup() via Team; posthog.schema (the pydantic models) is
# runtime-imported in the functions that build modifier objects to keep it off that path.
if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers

    from posthog.models import Team, User


@overload
def alias_poe_mode_for_legacy(persons_on_events_mode: PersonsOnEventsMode) -> PersonsOnEventsMode: ...
@overload
def alias_poe_mode_for_legacy(persons_on_events_mode: PersonsOnEventsMode | None) -> PersonsOnEventsMode | None: ...
def alias_poe_mode_for_legacy(persons_on_events_mode: PersonsOnEventsMode | None) -> PersonsOnEventsMode | None:
    if persons_on_events_mode == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED:
        # PERSON_ID_OVERRIDE_PROPERTIES_JOINED is not implemented in legacy insights
        # It's functionally the same as DISABLED, just slower - hence aliasing to DISABLED
        return PersonsOnEventsMode.DISABLED
    return persons_on_events_mode


def create_default_modifiers_for_user(
    user: "User", team: "Team", modifiers: Optional["HogQLQueryModifiers"] = None
) -> "HogQLQueryModifiers":
    from posthog.schema import HogQLQueryModifiers  # noqa: PLC0415

    if modifiers is None:
        modifiers = HogQLQueryModifiers()
    else:
        modifiers = modifiers.model_copy()

    return create_default_modifiers_for_team(team, modifiers)


def create_default_modifiers_for_team(
    team: "Team", modifiers: Optional["HogQLQueryModifiers"] = None
) -> "HogQLQueryModifiers":
    from pydantic import ValidationError  # noqa: PLC0415

    from posthog.schema import CustomChannelRule, HogQLQueryModifiers  # noqa: PLC0415

    if modifiers is None:
        modifiers = HogQLQueryModifiers()
    else:
        modifiers = modifiers.model_copy()

    if modifiers.useMaterializedViews is None:
        modifiers.useMaterializedViews = True

    if isinstance(team.modifiers, dict):
        for key, value in team.modifiers.items():
            if getattr(modifiers, key, None) is None:
                if key == "customChannelTypeRules":
                    # don't break all queries if customChannelTypeRules are invalid
                    try:
                        if isinstance(value, list):
                            value = [CustomChannelRule(**rule) if isinstance(rule, dict) else rule for rule in value]
                            setattr(modifiers, key, value)
                    except ValidationError:
                        pass
                elif key == "customBotDefinitions":
                    # upcast_rules reads both the current and the pre-combiner flat shape, and
                    # drops the entries that don't parse — one bad entry should not take a
                    # project's whole bot list out of every query.
                    from products.web_analytics.backend.hogql_queries.custom_bot_definitions import (  # noqa: PLC0415
                        upcast_rules,
                    )

                    if isinstance(value, list):
                        setattr(modifiers, key, upcast_rules(value))
                else:
                    setattr(modifiers, key, value)

    if modifiers.optimizeProjections is None:
        modifiers.optimizeProjections = True

    set_default_modifier_values(modifiers, team)

    return modifiers


def set_default_modifier_values(modifiers: "HogQLQueryModifiers", team: "Team"):
    if modifiers.personsOnEventsMode is None:
        modifiers.personsOnEventsMode = team.person_on_events_mode_flag_based_default

    if modifiers.personsArgMaxVersion is None:
        modifiers.personsArgMaxVersion = PersonsArgMaxVersion.AUTO

    if modifiers.inCohortVia is None:
        modifiers.inCohortVia = InCohortVia.AUTO

    if modifiers.materializationMode is None or modifiers.materializationMode == MaterializationMode.AUTO:
        modifiers.materializationMode = MaterializationMode.LEGACY_NULL_AS_NULL

    if modifiers.optimizeJoinedFilters is None:
        modifiers.optimizeJoinedFilters = False

    # typeAwareCastSimplification deliberately gets no explicit default: None is falsy at the
    # printer gate, stays out of the serialized cache payload (an explicit False would change every
    # query's cache key on deploy for zero behavior change), and remains overridable per team via
    # team.modifiers. Flipping the default on is a deliberate follow-up that carries the emitted-SQL
    # snapshot churn for review.

    if modifiers.bounceRatePageViewMode is None:
        modifiers.bounceRatePageViewMode = BounceRatePageViewMode.COUNT_PAGEVIEWS

    if modifiers.sessionTableVersion is None:
        modifiers.sessionTableVersion = SessionTableVersion.AUTO

    if modifiers.sessionsV2JoinMode is None:
        modifiers.sessionsV2JoinMode = SessionsV2JoinMode.UUID

    if modifiers.useMaterializedViews is None:
        modifiers.useMaterializedViews = True

    if modifiers.propertyGroupsMode is None and is_cloud():
        modifiers.propertyGroupsMode = PropertyGroupsMode.OPTIMIZED

    if modifiers.convertToProjectTimezone is None:
        modifiers.convertToProjectTimezone = True

    if modifiers.inlineCohortCalculation is None:
        modifiers.inlineCohortCalculation = InlineCohortCalculation.AUTO

    if modifiers.sessionIdPushdown is None:
        modifiers.sessionIdPushdown = False

    if modifiers.sessionPropertyPreAggregation is None:
        modifiers.sessionPropertyPreAggregation = False


def set_default_in_cohort_via(modifiers: "HogQLQueryModifiers") -> "HogQLQueryModifiers":
    if modifiers.inCohortVia is None or modifiers.inCohortVia == InCohortVia.AUTO:
        modifiers.inCohortVia = InCohortVia.SUBQUERY

    return modifiers
