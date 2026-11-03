"""The enabled hog functions that use an integration row. The integrations SDK loads this module."""

from posthog.integrations import IntegrationUsage

from products.cdp.backend.services.integration_usage import get_enabled_hog_functions_using_integration

HOG_FUNCTION_USAGE_TYPE = "hog_function"


def integration_usages(team_id: int, integration_id: int) -> list[IntegrationUsage]:
    return [
        IntegrationUsage(type=HOG_FUNCTION_USAGE_TYPE, id=str(function.id), name=function.name or str(function.id))
        for function in get_enabled_hog_functions_using_integration(team_id=team_id, integration_id=integration_id)
    ]
