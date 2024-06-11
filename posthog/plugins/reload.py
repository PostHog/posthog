import json
from typing import Union
import structlog
from django.conf import settings

from posthog.redis import get_client


logger = structlog.get_logger(__name__)

# NOTE: Any message publishing to the workers should be done here so that it is easy to find and update if needed


def publish_message(channel: str, payload: Union[dict, str]):
    message = json.dumps(payload) if not isinstance(payload, str) else payload

    get_client(settings.PLUGINS_RELOAD_REDIS_URL).publish(channel, message)


def reload_plugins_on_workers():
    logger.info("Reloading plugins on workers")
    publish_message(settings.PLUGINS_RELOAD_PUBSUB_CHANNEL, "reload!")


def reload_action_on_workers(team_id: int, action_id: int):
    logger.info(f"Reloading action {action_id} on workers")
    publish_message("reload-action", {"teamId": team_id, "actionId": action_id})


def drop_action_on_workers(team_id: int, action_id: int):
    logger.info(f"Dropping action {action_id} on workers")
    publish_message("drop-action", {"teamId": team_id, "actionId": action_id})


def reload_hog_functions_on_workers(team_id: int, hog_function_ids: list[str]):
    logger.info(f"Reloading hog functions {hog_function_ids} on workers")
    publish_message("reload-hog-functions", {"teamId": team_id, "hogFunctionIds": hog_function_ids})


def reset_available_product_features_cache_on_workers(organization_id: str):
    logger.info(f"Resetting available product features cache for organization {organization_id}")
    publish_message(
        "reset-available-product-features-cache",
        {"organization_id": organization_id},
    )


def populate_plugin_capabilities_on_workers(plugin_id: str):
    publish_message("populate-plugin-capabilities", {"plugin_id": plugin_id})
