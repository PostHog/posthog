from posthog.api.routing import RouterRegistry

from products.customer_analytics.backend.api.organization_members import OrganizationMembersForAccountViewSet
from products.customer_analytics.backend.api.views import (
    AccountNotebookViewSet,
    AccountViewSet,
    CustomerJourneyViewSet,
    CustomerProfileConfigViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"organization_members",
        OrganizationMembersForAccountViewSet,
        "project_organization_members",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"customer_profile_configs",
        CustomerProfileConfigViewSet,
        "project_customer_profile_configs",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"customer_journeys", CustomerJourneyViewSet, "project_customer_journeys", ["team_id"]
    )
    project_accounts_router, environment_accounts_router = routers.register_legacy_dual_route(
        r"accounts", AccountViewSet, "project_accounts", ["team_id"]
    )
    environment_accounts_router.register(
        r"notebooks", AccountNotebookViewSet, "environment_account_notebooks", ["team_id", "account_id"]
    )
    project_accounts_router.register(
        r"notebooks", AccountNotebookViewSet, "project_account_notebooks", ["team_id", "account_id"]
    )
