import json
from typing import Union
import requests
import structlog
from posthog.redis import get_client
from posthog.settings import CDP_FUNCTION_EXECUTOR_API_URL, PLUGINS_RELOAD_PUBSUB_CHANNEL, PLUGINS_RELOAD_REDIS_URL


logger = structlog.get_logger(__name__)

# NOTE: Any message publishing to the workers should be done here so that it is easy to find and update if needed


def publish_message(channel: str, payload: Union[dict, str]):
    message = json.dumps(payload) if not isinstance(payload, str) else payload
    get_client(PLUGINS_RELOAD_REDIS_URL).publish(channel, message)


def reload_plugins_on_workers():
    logger.info("Reloading plugins on workers")

    publish_message(PLUGINS_RELOAD_PUBSUB_CHANNEL, "reload!")


def reload_action_on_workers(team_id: int, action_id: int):
    logger.info(f"Reloading action {action_id} on workers")
    publish_message("reload-action", {"teamId": team_id, "actionId": action_id})


def drop_action_on_workers(team_id: int, action_id: int):
    logger.info(f"Dropping action {action_id} on workers")
    publish_message("drop-action", {"teamId": team_id, "actionId": action_id})


def reload_hog_functions_on_workers(team_id: int, hog_function_ids: list[str]):
    logger.info(f"Reloading hog functions {hog_function_ids} on workers")
    publish_message("reload-hog-functions", {"teamId": team_id, "hogFunctionIds": hog_function_ids})


def reload_all_hog_functions_on_workers():
    logger.info(f"Reloading all hog functionson workers")
    publish_message("reload-all-hog-functions", {})


def reload_integrations_on_workers(team_id: int, integration_ids: list[int]):
    logger.info(f"Reloading integrations {integration_ids} on workers")
    publish_message("reload-integrations", {"teamId": team_id, "integrationIds": integration_ids})


def reset_available_product_features_cache_on_workers(organization_id: str):
    logger.info(f"Resetting available product features cache for organization {organization_id} on workers")
    publish_message(
        "reset-available-product-features-cache",
        {"organization_id": organization_id},
    )


def populate_plugin_capabilities_on_workers(plugin_id: str):
    logger.info(f"Populating plugin capabilities for plugin {plugin_id} on workers")
    publish_message("populate-plugin-capabilities", {"plugin_id": plugin_id})


def create_hog_invocation_test(
    team_id: int,
    hog_function_id: str,
    globals: dict,
    configuration: dict,
    mock_async_functions: bool,
) -> requests.Response:
    logger.info(f"Creating hog invocation test for hog function {hog_function_id} on workers")
    return requests.post(
        CDP_FUNCTION_EXECUTOR_API_URL + f"/api/projects/{team_id}/hog_functions/{hog_function_id}/invocations",
        json={
            "globals": globals,
            "configuration": configuration,
            "mock_async_functions": mock_async_functions,
        },
    )


def get_hog_function_status(team_id: int, hog_function_id: str) -> requests.Response:
    return requests.get(
        CDP_FUNCTION_EXECUTOR_API_URL + f"/api/projects/{team_id}/hog_functions/{hog_function_id}/status"
    )


def patch_hog_function_status(team_id: int, hog_function_id: str, state: int) -> requests.Response:
    return requests.patch(
        CDP_FUNCTION_EXECUTOR_API_URL + f"/api/projects/{team_id}/hog_functions/{hog_function_id}/status",
        json={"state": state},
    )
