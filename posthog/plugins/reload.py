from posthog.cache import get_redis_instance


def reload_plugins_on_workers():
    redis_instance = get_redis_instance()
    redis_instance.publish("reload-plugins", "reload!")
