"""
Synthesize a minimal valid POST body for a DRF serializer.

Phase 5b cross-tenant FK in POST tests need to send a request body that
will pass the serializer's required-field validation, then they inject a
victim's tenant FK into one specific field and verify it gets rejected.

`build_minimal_post_body(serializer_cls, team)` walks the serializer's
field set and fills required, writable fields with sensible defaults.
For tenant FK targets, it builds an attacker-owned instance via
`build_minimal_instance` and returns the pk. If a required field can't
be filled (custom field type, unknown choice constraints, etc.), it
raises `BodyUnfillable` — the caller skips the test rather than
asserting a false negative.

A registry of per-viewset body factories takes precedence over the
generic synthesis. Register hard cases (custom validators, mutually-
exclusive fields, business-logic constraints) in `post_body_fixtures.py`.
"""

from __future__ import annotations

import uuid
import datetime
from typing import Any

from django.db import models
from django.utils import timezone

from rest_framework import serializers

from posthog.models.team import Team
from posthog.test.idor.factory import build_minimal_instance, current_sentinel
from posthog.test.idor.fk_target_models import classify_model_scope


class BodyUnfillable(ValueError):
    """Raised when `build_minimal_post_body` can't satisfy a required field."""


def build_minimal_post_body(
    serializer_cls: type[serializers.Serializer],
    team: Team,
) -> dict[str, Any]:
    """Return a dict that should pass the serializer's required-field validation.

    Resolution order:
      1. Per-viewset body fixture in `posthog.test.idor.post_body_fixtures` (if registered)
      2. Generic introspection via DRF field walk
      3. `BodyUnfillable` is raised — the caller should skip the test.
    """
    # Registry takes precedence — it handles serializers with custom validate()
    # methods or shape constraints DRF introspection can't see.
    from posthog.test.idor.post_body_fixtures import get_post_body_fixture

    fixture = get_post_body_fixture(serializer_cls)
    if fixture is not None:
        return fixture(team)

    instance = serializer_cls(context={"team_id": team.pk, "request": None, "get_team": lambda: team})
    return _walk_serializer_for_body(instance, team)


def _walk_serializer_for_body(instance: serializers.Serializer, team: Team) -> dict[str, Any]:
    """Walk a serializer's writable required fields and synthesize values."""
    body: dict[str, Any] = {}
    try:
        fields = dict(instance.fields)
    except Exception as exc:
        raise BodyUnfillable(f"could not enumerate serializer fields ({type(exc).__name__}: {exc})") from exc

    for field_name, drf_field in fields.items():
        if drf_field.read_only:
            continue
        if not drf_field.required:
            # Skip optional fields — they don't gate validation. Including them
            # adds risk of tripping a value-shape constraint we couldn't predict.
            continue
        body[field_name] = _default_for_serializer_field(field_name, drf_field, team)
    return body


def _default_for_serializer_field(field_name: str, drf_field: serializers.Field, team: Team) -> Any:
    """Synthesize a default value for a single required serializer field."""
    # Order matters: ChoiceField is a CharField subclass, ManyRelatedField wraps PrimaryKeyRelatedField, etc.
    if isinstance(drf_field, serializers.ChoiceField):
        choices = list(drf_field.choices)
        if not choices:
            raise BodyUnfillable(f"{field_name}: ChoiceField with no choices")
        return choices[0]
    if isinstance(drf_field, serializers.ManyRelatedField):
        return []
    if isinstance(drf_field, serializers.PrimaryKeyRelatedField):
        return _build_fk_default(field_name, drf_field, team)
    if isinstance(drf_field, serializers.EmailField):
        return "idor@example.com"
    if isinstance(drf_field, (serializers.CharField, serializers.SlugField, serializers.URLField)):
        max_len = getattr(drf_field, "max_length", None) or 64
        return current_sentinel()[:max_len] or "idor"
    if isinstance(drf_field, serializers.UUIDField):
        return str(uuid.uuid4())
    if isinstance(drf_field, (serializers.IntegerField, serializers.FloatField)):
        return 0
    if isinstance(drf_field, serializers.BooleanField):
        return False
    if isinstance(drf_field, serializers.DateTimeField):
        return timezone.now().isoformat()
    if isinstance(drf_field, serializers.DateField):
        return datetime.date.today().isoformat()
    if isinstance(drf_field, (serializers.JSONField, serializers.DictField)):
        return {}
    if isinstance(drf_field, serializers.ListField):
        return []
    if isinstance(drf_field, serializers.ModelSerializer):
        # Recurse one level — same depth boundary as fk_discovery.
        return _walk_serializer_for_body(drf_field, team)
    raise BodyUnfillable(f"{field_name}: no default for {type(drf_field).__name__}; register a body fixture or skip")


def _build_fk_default(field_name: str, drf_field: serializers.PrimaryKeyRelatedField, team: Team) -> Any:
    """For a PK field, build an attacker-owned target instance and return its pk."""
    qs = getattr(drf_field, "queryset", None)
    target = getattr(qs, "model", None) if qs is not None else None
    if target is None or not isinstance(target, type) or not issubclass(target, models.Model):
        raise BodyUnfillable(f"{field_name}: PK field has no resolvable queryset.model")
    # Tenant-root models (Team, Project, Organization) aren't in the
    # tenant-scoped allowlist because they ARE the tenant. The right
    # synthesis is the test team itself — it's already attacker-owned.
    if target.__name__ == "Team":
        return team.pk
    if target.__name__ == "Project":
        return team.project_id
    if target.__name__ == "Organization":
        return team.organization_id
    # If target isn't tenant-scoped (e.g. User globally), there's no fixture
    # plumbing for it. Either build_minimal_instance handles it or we skip.
    if classify_model_scope(target.__name__) is None:
        raise BodyUnfillable(
            f"{field_name}: PK target {target.__name__} is not tenant-scoped; can't synthesize default"
        )
    try:
        attacker_instance = build_minimal_instance(target, team=team)
    except Exception as exc:
        raise BodyUnfillable(
            f"{field_name}: could not build attacker {target.__name__} ({type(exc).__name__}: {exc})"
        ) from exc
    return attacker_instance.pk
