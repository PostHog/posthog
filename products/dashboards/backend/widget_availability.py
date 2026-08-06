from __future__ import annotations

from typing import TYPE_CHECKING

from products.dashboards.backend.widget_specs.registry import get_widget_spec

if TYPE_CHECKING:
    from posthog.models.team import Team


def is_widget_availability_requirement_met(requirement: str, team: Team) -> bool | None:
    """Whether a single widget availability requirement is satisfied for the team.

    Mirrors the frontend `isWidgetAvailabilityRequirementMet`. Returns None for an
    unrecognized requirement so callers can treat it as "unknown" rather than "unmet".
    """
    if requirement == "session_replay_enabled":
        return bool(team.session_recording_opt_in)
    if requirement == "exception_autocapture":
        # Reflects the team opt-in only. The widget UI additionally treats "has received
        # exceptions" as enabled, so a team ingesting exceptions without the opt-in flag
        # reads as not-enabled here. We avoid the events-received check to keep this off
        # the hot widget-add path (no ClickHouse query).
        return bool(team.autocapture_exceptions_opt_in)
    return None


def get_widget_feature_enabled(widget_type: str, team: Team) -> bool | None:
    """Whether the feature(s) a widget depends on are enabled for the team.

    Recorded at widget-add time so we can tell whether the user saw real data or the
    setup/custom view. Returns None when the widget declares no availability
    requirements or any requirement is unrecognized.
    """
    spec = get_widget_spec(widget_type)
    if spec is None or not spec.availability_requirements:
        return None

    results = [is_widget_availability_requirement_met(req, team) for req in spec.availability_requirements]
    # An unrecognized requirement is "unknown", not "met" — we can't confirm the feature is on, so
    # don't silently drop it and risk emitting feature_enabled=True. Report the whole widget as unknown.
    if any(result is None for result in results):
        return None
    return all(results)
