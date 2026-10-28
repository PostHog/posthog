import posthoganalytics

from posthog.models.team import Team

from products.customer_analytics.backend.constants import CUSTOMER_ANALYTICS_CSP_FLAG


def is_customer_analytics_active(team: Team, *, raise_on_unknown: bool = False) -> bool:
    organization_id = str(team.organization_id)
    enabled = posthoganalytics.feature_enabled(
        CUSTOMER_ANALYTICS_CSP_FLAG,
        organization_id,
        groups={"organization": organization_id},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )
    if enabled is None and raise_on_unknown:
        raise RuntimeError("Customer analytics flag evaluation is unavailable")
    return bool(enabled)
