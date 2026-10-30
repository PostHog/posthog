from posthog.api.routing import RouterRegistry

from products.account_audits.backend.presentation.views import AccountAuditStartViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.root.register(r"account_audits", AccountAuditStartViewSet, "account_audits")
