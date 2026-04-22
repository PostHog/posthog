"""
Minimal-instance factory for IDOR tests.

`build_minimal_instance(Model, team, **overrides)` creates the simplest
possible valid instance of `Model` scoped to `team`, using Django field
introspection to fill in required fields. Caller-supplied overrides
always win.

When a required field can't be filled automatically (e.g. a non-nullable
ForeignKey without a default), we raise `UnfillableField`. Callers can
catch this and either skip the test or consult the fixture registry.

**Sentinel embedding**: Each auto-built instance has `current_sentinel()`
embedded in its string fields so the test can later verify the sentinel
does not appear in the attacker's response body (info-leak check).
Call `reset_sentinel()` at the start of each test to get a unique value.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.db import models
from django.utils import timezone

from posthog.models.team import Team

# Prefix for auto-generated sentinels. Tests can detect this pattern in
# response bodies to flag an info-leak even when status code is 200/500/etc.
_SENTINEL_PREFIX = "idor-sentinel-"
_current_sentinel: str = _SENTINEL_PREFIX + "boot"


def reset_sentinel() -> str:
    """Generate a new unique sentinel. Call once per test."""
    global _current_sentinel
    _current_sentinel = _SENTINEL_PREFIX + uuid.uuid4().hex[:12]
    return _current_sentinel


def current_sentinel() -> str:
    return _current_sentinel


# Short enough to fit in most CharField(max_length=...) constraints but long
# enough to appear distinctive in test output.
DEFAULT_SENTINEL = current_sentinel


class UnfillableField(ValueError):
    """Raised when `build_minimal_instance` cannot auto-generate a required field."""


def build_minimal_instance(
    model_cls: type[models.Model],
    team: Team,
    **overrides: Any,
) -> models.Model:
    """Create the simplest valid instance of `model_cls` for `team`.

    Resolution order:
      1. Registered fixture in `posthog.test.idor.fixtures` (if present)
      2. Auto-build via Django field introspection
      3. `UnfillableField` is raised — the caller should skip the test.

    Overrides always take precedence when auto-building. M2M fields are
    skipped (they must be attached after create via `.add()`).
    """
    # Fixture registry takes precedence when present — it handles the hard
    # cases (required FKs, custom validators) where introspection can't cope.
    if not overrides:
        from posthog.test.idor.fixtures import get_fixture

        fixture = get_fixture(model_cls)
        if fixture is not None:
            return fixture(team)

    kwargs: dict[str, Any] = {}

    for field in model_cls._meta.get_fields():
        if not isinstance(field, models.Field):
            continue
        if field.auto_created:
            continue
        if getattr(field, "primary_key", False):
            continue
        # M2M fields can't be set at create() time; callers that need them
        # should create the instance then .add() separately.
        if isinstance(field, models.ManyToManyField):
            continue

        name = field.name
        if name in overrides:
            continue

        if name == "team":
            kwargs[name] = team
            continue

        if getattr(field, "null", False) or field.has_default():
            continue

        kwargs[name] = _default_for_field(field, model_cls)

    kwargs.update(overrides)
    return model_cls.objects.create(**kwargs)


def _default_for_field(field: models.Field, model_cls: type) -> Any:
    """Generate a minimal valid value for a required field."""
    if isinstance(field, models.EmailField):
        return "idor@example.com"
    if isinstance(field, (models.CharField, models.TextField, models.SlugField, models.URLField)):
        max_len = getattr(field, "max_length", None) or 64
        # Embed the current sentinel so tests can detect info-leaks in responses.
        return current_sentinel()[:max_len]
    if isinstance(field, (models.IntegerField, models.BigIntegerField, models.SmallIntegerField)):
        return 0
    if isinstance(field, models.FloatField):
        return 0.0
    if isinstance(field, models.BooleanField):
        return False
    if isinstance(field, models.DateTimeField):
        return timezone.now()
    if isinstance(field, models.DateField):
        return timezone.now().date()
    if isinstance(field, models.JSONField):
        return {}
    if isinstance(field, models.UUIDField):
        return uuid.uuid4()
    if isinstance(field, models.ForeignKey):
        raise UnfillableField(
            f"ForeignKey {field.name!r} on {model_cls.__name__} has no default; "
            f"supply an override (or add a fixture registry entry)"
        )
    raise UnfillableField(
        f"Cannot auto-generate value for {type(field).__name__} {field.name!r} on {model_cls.__name__}"
    )
