"""Cut Django overhead that dominates a from-scratch ``migrate``.

A full migrate spends most of its time in Python, rendering historical model states: each
operation clones fields and rebuilds the models that relate to the one it changes. Two Django
hot spots in that loop do repeated work that gives the same result every time. Applied once from
``PostHogConfig.ready()``; both patches keep Django's return values.

Swappable-settings cache:
Django caches ``Apps.get_swappable_settings_name`` with ``functools.cache`` on the class, so one
cache serves every ``Apps`` instance. Migration state rendering builds ``StateApps`` instances and
calls ``clear_cache()`` on them each time it registers a model, which also empties the entry for
the global registry. Every ``ForeignKey.deconstruct()`` asks the global registry for its swappable
setting, so each field clone then scans all installed models again. The fix binds a cache to the
global registry instance. The instance attribute shadows the class cache, so a
``StateApps.clear_cache()`` no longer reaches it. ``apps.clear_cache()`` on the global registry
(tests that swap settings or isolate apps) still clears it, because ``clear_cache`` resolves
``self.get_swappable_settings_name`` to this instance cache.

Field choices:
``Field.__init__`` passes ``choices`` through ``normalize_choices`` for every field, and most fields
have ``choices=None``. For ``None`` that function runs a local import, which raises and catches an
``AttributeError`` in the ``enums`` module ``__getattr__``, then a chain of ABC ``isinstance``
checks, only to return ``None``. The fix returns ``None`` at once and passes all other values to
Django's function.
"""

import inspect
import functools
from typing import Any

from django.apps import apps
from django.apps.registry import Apps
from django.db.models import fields as model_fields
from django.utils.choices import normalize_choices

_patched = False


def _normalize_choices(value: Any, *, depth: int = 0) -> Any:
    if value is None:
        return None
    return normalize_choices(value, depth=depth)


def apply() -> None:
    """Apply both speedups. Idempotent; safe to call more than once."""
    global _patched
    if _patched:
        return
    uncached = inspect.unwrap(Apps.get_swappable_settings_name)
    # setattr keeps mypy from flagging the assignment of a method on an instance.
    setattr(apps, "get_swappable_settings_name", functools.cache(functools.partial(uncached, apps)))  # noqa: B010
    setattr(model_fields, "normalize_choices", _normalize_choices)  # noqa: B010
    _patched = True
