import structlog
from django.conf import settings

from posthog.redis import get_client

logger = structlog.get_logger(__name__)


def reload_plugins_on_workers():
    logger.info("Reloading plugins on workers")
    get_client(settings.PLUGINS_RELOAD_REDIS_URL).publish(settings.PLUGINS_RELOAD_PUBSUB_CHANNEL, "reload!")
