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


class _PerViewerWidgetQueryThrottle(PersonalApiKeyRateThrottle):
    """Keyed per signed-in viewer, so one member's loads or refresh loop can't use up the team's budget."""

    def allow_request(self, request, view) -> bool:
        return self._allow_request_internal(request, view, personal_api_key_only=False)

    def get_cache_key(self, request, view):
        if request.user.is_authenticated:
            return self.cache_format % {"scope": self.scope, "ident": request.user.pk}
        return super().get_cache_key(request, view)


class DashboardChartWidgetQueryBurstRateThrottle(_PerViewerWidgetQueryThrottle):
    """Per-viewer burst cap on chart widget runs from a browser session (a 20-tile dashboard loads 6 times)."""

    scope = "dashboard_chart_widget_query_burst"
    rate = "120/minute"


class DashboardChartWidgetQuerySustainedRateThrottle(_PerViewerWidgetQueryThrottle):
    """Per-viewer sustained cap on chart widget runs from a browser session."""

    scope = "dashboard_chart_widget_query_sustained"
    rate = "1200/hour"


def get_dashboard_widget_query_throttle_error(request, view) -> str | None:
    """Return a client-facing error when dashboard widget query throttles would block this request."""
    return _throttle_error(
        request, view, (DashboardWidgetQueryBurstRateThrottle, DashboardWidgetQuerySustainedRateThrottle)
    )


def get_dashboard_chart_widget_session_throttle_error(request, view) -> str | None:
    """Return a client-facing error when the per-viewer chart widget throttles would block this session request."""
    return _throttle_error(
        request, view, (DashboardChartWidgetQueryBurstRateThrottle, DashboardChartWidgetQuerySustainedRateThrottle)
    )


def _throttle_error(request, view, throttle_classes: tuple[type[PersonalApiKeyRateThrottle], ...]) -> str | None:
    if not is_rate_limit_enabled(round(time.time() / 60)):
        return None

    team_id = PersonalApiKeyRateThrottle.safely_get_team_id_from_view(view)
    if team_id is not None and team_is_allowed_to_bypass_throttle(team_id):
        return None

    for throttle_cls in throttle_classes:
        throttle = throttle_cls()
        if throttle.allow_request(request, view):
            continue
        wait = throttle.wait()
        if wait:
            return f"Rate limit exceeded. Expected available in {wait} seconds."
        return "Rate limit exceeded. Try again later."
    return None
