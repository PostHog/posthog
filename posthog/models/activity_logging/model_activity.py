from threading import local
from typing import Any
from django.db import models
from posthog.models.signals import model_activity_signal
from loginas.utils import is_impersonated_session

_thread_local = local()


def get_was_impersonated():
    return getattr(_thread_local, "was_impersonated", False)


class ModelActivityMixin(models.Model):
    """
    A mixin that automatically sends activity signals when a model is created or updated.
    The model's class name will be used as the scope for activity logging.
    """

    class Meta:
        # This is a mixin, so we don't need to create a table for it
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Get a copy of the existing instance before saving
        if self.pk:
            before_update = self.__class__.objects.filter(pk=self.pk).first()  # type: ignore[attr-defined]
            if before_update:
                before_update._state.adding = False  # Ensure the copy knows it's not a new instance
                before_update.pk = before_update.pk  # Ensure pk is copied
        else:
            before_update = None

        change_type = "updated" if self.pk else "created"

        super().save(*args, **kwargs)

        model_activity_signal.send(
            sender=self.__class__,
            scope=self.__class__.__name__,
            before_update=before_update,
            after_update=self,
            activity=change_type,
            was_impersonated=get_was_impersonated(),
        )


class ImpersonatedContext:
    # This is a context manager that sets the was_impersonated flag in the thread local storage
    # if the request is impersonated. Use this to call the model's save method with impersonated
    # info from the request if you have a request available. This is pretty much a no-op if you
    # don't have a request available.
    def __init__(self, request):
        self.was_impersonated = is_impersonated_session(request) if request else False

    def __enter__(self):
        if self.was_impersonated:
            _thread_local.was_impersonated = True
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.was_impersonated and hasattr(_thread_local, "was_impersonated"):
            delattr(_thread_local, "was_impersonated")
