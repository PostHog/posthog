from typing import Any

from django.db import models

from posthog.models.activity_logging.utils import activity_storage, get_changed_fields_local
from posthog.models.signals import model_activity_signal


def get_was_impersonated():
    return activity_storage.get_was_impersonated()


def get_current_user():
    return activity_storage.get_user()


def is_impersonated_session(request):
    """Lazy import to avoid circular import issues during Django setup"""
    try:
        from loginas.utils import is_impersonated_session as _is_impersonated_session

        return _is_impersonated_session(request)
    except ImportError:
        return False


class ModelActivityMixin(models.Model):
    """
    A mixin that automatically sends activity signals when a model is created or updated.
    The model's class name will be used as the scope for activity logging.
    """

    class Meta:
        # This is a mixin, so we don't need to create a table for it
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        change_type = "created" if self._state.adding else "updated"
        should_log = True
        before_update = None

        # For updates, check if we need activity logging at all
        if change_type == "updated":
            should_log, before_update = self._should_log_activity_for_update(**kwargs)

        super().save(*args, **kwargs)

        if should_log:
            model_activity_signal.send(
                sender=self.__class__,
                scope=self.__class__.__name__,
                before_update=before_update,
                after_update=self,
                activity=change_type,
                user=get_current_user(),
                was_impersonated=get_was_impersonated(),
            )

    def _get_before_update(self, **kwargs) -> Any:
        before_update = None
        # Get a copy of the existing instance before saving
        if self.pk:
            before_update = self.__class__.objects.filter(pk=self.pk).first()  # type: ignore[attr-defined]
            if before_update:
                before_update._state.adding = False  # Ensure the copy knows it's not a new instance
                before_update.pk = before_update.pk  # Ensure pk is copied
        else:
            before_update = None

        return before_update

    def _should_log_activity_for_update(self, **kwargs) -> tuple[bool, Any]:
        from typing import cast

        from posthog.models.activity_logging.activity_log import ActivityScope, signal_exclusions

        model_name = cast(ActivityScope, self.__class__.__name__)
        signal_excluded_fields = signal_exclusions.get(model_name, [])

        if not signal_excluded_fields:
            return True, self._get_before_update()

        update_fields = kwargs.get("update_fields")
        if update_fields and all(field in signal_excluded_fields for field in update_fields):
            return False, None

        before_update = self._get_before_update()
        if not before_update:
            return True, None

        changed_fields = get_changed_fields_local(before_update, self)
        should_log = len(changed_fields) > 0

        return should_log, before_update


class ImpersonatedContext:
    # This is a context manager that sets the was_impersonated flag in the activity storage
    # if the request is impersonated. Use this to call the model's save method with impersonated
    # info from the request if you have a request available. This is pretty much a no-op if you
    # don't have a request available.
    def __init__(self, request):
        self.was_impersonated = is_impersonated_session(request) if request else False

    def __enter__(self):
        if self.was_impersonated:
            activity_storage.set_was_impersonated(True)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.was_impersonated:
            activity_storage.clear_was_impersonated()
