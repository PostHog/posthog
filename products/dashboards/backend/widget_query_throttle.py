"""Rate limits for dashboard run_widgets (ClickHouse-backed widget queries)."""

from __future__ import annotations

import time

from posthog.rate_limit import PersonalApiKeyRateThrottle, is_rate_limit_enabled, team_is_allowed_to_bypass_throttle


class DashboardWidgetQueryBurstRateThrottle(PersonalApiKeyRateThrottle):
    """Per-team burst cap on dashboard widget data fetches (web session and API keys)."""

    scope = "dashboard_widget_query_burst"
    rate = "120/minute"

    def allow_request(self, request, view) -> bool:
        return self._allow_request_internal(request, view, personal_api_key_only=False)


class DashboardWidgetQuerySustainedRateThrottle(PersonalApiKeyRateThrottle):
    """Per-team sustained cap on dashboard widget data fetches."""

    scope = "dashboard_widget_query_sustained"
    rate = "600/hour"

    def allow_request(self, request, view) -> bool:
        return self._allow_request_internal(request, view, personal_api_key_only=False)


def get_dashboard_widget_query_throttle_error(request, view) -> str | None:
    """Return a client-facing error when dashboard widget query throttles would block this request."""
    if not is_rate_limit_enabled(round(time.time() / 60)):
        return None

    team_id = PersonalApiKeyRateThrottle.safely_get_team_id_from_view(view)
    if team_id is not None and team_is_allowed_to_bypass_throttle(team_id):
        return None

    for throttle_cls in (DashboardWidgetQueryBurstRateThrottle, DashboardWidgetQuerySustainedRateThrottle):
        throttle = throttle_cls()
        if throttle.allow_request(request, view):
            continue
        wait = throttle.wait()
        if wait:
            return f"Rate limit exceeded. Expected available in {wait} seconds."
        return "Rate limit exceeded. Try again later."
    return None
