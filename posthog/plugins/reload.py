from posthog.redis import get_client
from posthog.settings import PLUGINS_RELOAD_PUBSUB_CHANNEL


def reload_plugins_on_workers():
    get_client().publish(PLUGINS_RELOAD_PUBSUB_CHANNEL, "reload!")
