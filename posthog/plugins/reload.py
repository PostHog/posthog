from django.conf import settings

from posthog.redis import get_client


def reload_plugins_on_workers():
    get_client().publish(settings.PLUGINS_RELOAD_PUBSUB_CHANNEL, "reload!")
