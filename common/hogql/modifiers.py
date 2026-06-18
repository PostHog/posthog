from typing import TYPE_CHECKING, Any, Optional

import posthoganalytics

from common.hogql.backend import resolve_backend_symbol as _resolve_backend_symbol

is_cloud = _resolve_backend_symbol("posthog.cloud_utils", "is_cloud")
BounceRatePageViewMode = _resolve_backend_symbol("posthog.schema_enums", "BounceRatePageViewMode")
InCohortVia = _resolve_backend_symbol("posthog.schema_enums", "InCohortVia")
InlineCohortCalculation = _resolve_backend_symbol("posthog.schema_enums", "InlineCohortCalculation")
MaterializationMode = _resolve_backend_symbol("posthog.schema_enums", "MaterializationMode")
PersonsArgMaxVersion = _resolve_backend_symbol("posthog.schema_enums", "PersonsArgMaxVersion")
PropertyGroupsMode = _resolve_backend_symbol("posthog.schema_enums", "PropertyGroupsMode")
SessionsV2JoinMode = _resolve_backend_symbol("posthog.schema_enums", "SessionsV2JoinMode")
SessionTableVersion = _resolve_backend_symbol("posthog.schema_enums", "SessionTableVersion")


# This module loads at django.setup() via Team; posthog.schema (the pydantic models) is
# runtime-imported in the functions that build modifier objects to keep it off that path.
if TYPE_CHECKING:
    HogQLQueryModifiers = Any
    Team = Any
    User = Any


def create_default_modifiers_for_user(
    user: "User", team: "Team", modifiers: Optional["HogQLQueryModifiers"] = None
) -> "HogQLQueryModifiers":
    HogQLQueryModifiers = _resolve_backend_symbol("posthog.schema", "HogQLQueryModifiers")

    if modifiers is None:
        modifiers = HogQLQueryModifiers()
    else:
        modifiers = modifiers.model_copy()

    modifiers.useMaterializedViews = posthoganalytics.feature_enabled(
        "data-modeling",
        str(user.distinct_id),
        person_properties={
            "email": user.email,
        },
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )

    return create_default_modifiers_for_team(team, modifiers)


def create_default_modifiers_for_team(
    team: "Team", modifiers: Optional["HogQLQueryModifiers"] = None
) -> "HogQLQueryModifiers":
    from pydantic import ValidationError  # noqa: PLC0415

    CustomChannelRule = _resolve_backend_symbol("posthog.schema", "CustomChannelRule")
    HogQLQueryModifiers = _resolve_backend_symbol("posthog.schema", "HogQLQueryModifiers")

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
