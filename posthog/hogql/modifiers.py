from typing import TYPE_CHECKING, Optional

import posthoganalytics
from pydantic import ValidationError

from posthog.cloud_utils import is_cloud
from posthog.schema import (
    HogQLQueryModifiers,
    InCohortVia,
    MaterializationMode,
    PersonsArgMaxVersion,
    BounceRatePageViewMode,
    PropertyGroupsMode,
    SessionTableVersion,
    CustomChannelRule,
    SessionsV2JoinMode,
    RevenueAnalyticsPersonsJoinModeModifier,
)

if TYPE_CHECKING:
    from posthog.models import Team
    from posthog.models import User


def create_default_modifiers_for_user(
    user: "User", team: "Team", modifiers: Optional[HogQLQueryModifiers] = None
) -> HogQLQueryModifiers:
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
    team: "Team", modifiers: Optional[HogQLQueryModifiers] = None
) -> HogQLQueryModifiers:
    if modifiers is None:
        modifiers = HogQLQueryModifiers()
    else:
        modifiers = modifiers.model_copy()

    if modifiers.useMaterializedViews is None:
        modifiers.useMaterializedViews = True

    if isinstance(team.modifiers, dict):
        for key, value in team.modifiers.items():
            if getattr(modifiers, key) is None:
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

    set_default_modifier_values(modifiers, team)

    return modifiers


def set_default_modifier_values(modifiers: HogQLQueryModifiers, team: "Team"):
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
        modifiers.sessionsV2JoinMode = SessionsV2JoinMode.STRING

    if modifiers.useMaterializedViews is None:
        modifiers.useMaterializedViews = True

    if modifiers.usePresortedEventsTable is None:
        modifiers.usePresortedEventsTable = False

    if modifiers.propertyGroupsMode is None and is_cloud():
        modifiers.propertyGroupsMode = PropertyGroupsMode.OPTIMIZED

    if modifiers.convertToProjectTimezone is None:
        modifiers.convertToProjectTimezone = True

    if modifiers.revenueAnalyticsPersonsJoinMode is None:
        modifiers.revenueAnalyticsPersonsJoinMode = RevenueAnalyticsPersonsJoinModeModifier.ID


def set_default_in_cohort_via(modifiers: HogQLQueryModifiers) -> HogQLQueryModifiers:
    if modifiers.inCohortVia is None or modifiers.inCohortVia == InCohortVia.AUTO:
        modifiers.inCohortVia = InCohortVia.SUBQUERY

    return modifiers
