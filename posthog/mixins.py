from rest_framework import mixins

from posthog.event_usage import report_user_action


def log_deletion_metadata_to_posthog(func):
    """
    wraps a DRF destroy endpoint and sends a PostHog event recording its deletion
    so:
        * args[0] is the ViewSet
        * args[1] is the HTTP request
    """

    def wrapper(*args, **kwargs):
        instance = args[0].get_object()
        user = args[1].user
        metadata = instance.get_analytics_metadata() if hasattr(instance, "get_analytics_metadata") else {}

        func_result = func(*args, **kwargs)

        report_user_action(user, f"{instance._meta.verbose_name} deleted", metadata)

        return func_result

    return wrapper


class AnalyticsDestroyModelMixin(mixins.DestroyModelMixin):
    """
    DestroyModelMixin enhancement that provides reporting of when an object is deleted.

    Generally this would be better off executed at the serializer level,
    but deletion (i.e. `destroy`) is performed directly in the viewset, which is why this mixin is a thing.
    """

    @log_deletion_metadata_to_posthog
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
