from posthog.api.routing import RouterRegistry

from products.customer_analytics.backend.api.views import (
    AccountNotebookViewSet,
    AccountViewSet,
    CustomerJourneyViewSet,
    CustomerProfileConfigViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    routers.environments.register(
        r"customer_profile_configs",
        CustomerProfileConfigViewSet,
        "environment_customer_profile_configs",
        ["team_id"],
    )
    routers.environments.register(
        r"customer_journeys",
        CustomerJourneyViewSet,
        "environment_customer_journeys",
        ["team_id"],
    )
    environment_accounts_router = routers.environments.register(
        r"accounts",
        AccountViewSet,
        "environment_accounts",
        ["team_id"],
    )
    environment_accounts_router.register(
        r"notebooks",
        AccountNotebookViewSet,
        "environment_account_notebooks",
        ["team_id", "account_id"],
    )
