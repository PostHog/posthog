"""Keeps the tasks search index in step with canvas rows.

The index belongs to the tasks product. Canvas owns its model, so canvas listens to
its own saves and calls the tasks facade, instead of tasks registering a receiver
on a foreign model.
"""

from collections.abc import Iterable
from typing import Any

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from products.canvas.backend.models import Canvas
from products.tasks.backend.facade import search_index as tasks_search_index


@receiver(post_save, sender=Canvas)
def canvas_saved(
    sender: type[Canvas], instance: Canvas, update_fields: Iterable[str] | None = None, **kwargs: Any
) -> None:
    tasks_search_index.canvas_saved(instance.id, update_fields)


@receiver(post_delete, sender=Canvas)
def canvas_deleted(sender: type[Canvas], instance: Canvas, **kwargs: Any) -> None:
    tasks_search_index.canvas_deleted(instance.id)
