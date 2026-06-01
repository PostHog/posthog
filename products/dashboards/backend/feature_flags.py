import posthoganalytics

DASHBOARD_WIDGETS_FLAG = "dashboard-widgets"


def dashboard_widgets_enabled(team_id: int) -> bool:
    return bool(posthoganalytics.feature_enabled(DASHBOARD_WIDGETS_FLAG, str(team_id)))
