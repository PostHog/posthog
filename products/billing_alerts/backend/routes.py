from posthog.api.routing import RouterRegistry

from products.billing_alerts.backend.presentation.views import BillingAlertViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.organizations.register(
        r"billing/alerts",
        BillingAlertViewSet,
        "organization_billing_alerts",
        ["organization_id"],
    )
