import json
import structlog
from django.conf import settings

from posthog.redis import get_client


logger = structlog.get_logger(__name__)


def reload_plugins_on_workers():
    logger.info("Reloading plugins on workers")
    get_client(settings.PLUGINS_RELOAD_REDIS_URL).publish(settings.PLUGINS_RELOAD_PUBSUB_CHANNEL, "reload!")


def reload_action_on_workers(team_id: int, action_id: int):
    logger.info(f"Reloading action {action_id} on workers")
    get_client(settings.PLUGINS_RELOAD_REDIS_URL).publish(
        "reload-action",
        json.dumps({"teamId": team_id, "actionId": action_id}),
    )


def drop_action_on_workers(team_id: int, action_id: int):
    logger.info(f"Dropping action {action_id} on workers")
    get_client(settings.PLUGINS_RELOAD_REDIS_URL).publish(
        "drop-action", json.dumps({"teamId": team_id, "actionId": action_id})
    )


def reload_hog_functions_on_workers(team_id: int, hog_function_ids: list[str]):
    logger.info(f"Reloading hog functions {hog_function_ids} on workers")
    get_client(settings.PLUGINS_RELOAD_REDIS_URL).publish(
        "reload-hog-functions",
        json.dumps({"teamId": team_id, "hogFunctionIds": hog_function_ids}),
    )
