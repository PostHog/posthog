from posthog.redis import get_client


def reload_plugins_on_workers():
    get_client().publish("reload-plugins", "reload!")
