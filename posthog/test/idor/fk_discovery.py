"""
Discover writable tenant-FK serializer fields.

Walks a DRF `ModelSerializer` (or generic `Serializer`) and emits one
`WritableFKField` per writable PrimaryKeyRelatedField (or nested
ModelSerializer one level deep) whose target model is tenant-scoped per
the semgrep allowlist. The emitted records drive the parametric
`test_cross_tenant_fk_in_patch` test.

Boundaries:

  - Top-level fields and **one** level of nested serializer fields. The
    common BatchExport-style "destination.id" case is depth 1; deeper
    nesting is rare and tracked as Phase 5c follow-up.
  - Read-only fields (`read_only=True` or in `Meta.read_only_fields`)
    are skipped — they can't be written via PATCH.
  - Fields whose target model is not tenant-scoped are skipped (e.g. a
    PK field pointing at User globally — but `OrganizationMembership`
    does count, since users are scoped to orgs).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal, Optional

from django.db import models

from rest_framework import serializers

from posthog.test.idor.fk_target_models import classify_model_scope

Scope = Literal["team", "organization", "user_in_org", "user_and_team"]


@dataclass(frozen=True)
class WritableFKField:
    """A writable serializer field that points at a tenant-scoped model."""

    serializer_field_name: str
    """The key in `Meta.fields` (what the client sends in JSON)."""

    source_attr: Optional[str]
    """`source=` if the field uses one, else None."""

    target_model: type[models.Model]
    """The Django model class the FK references."""

    scope: Scope
    """Tenant scope of the target model."""

    is_already_scoped: bool
    """True if the field is a TeamScopedPrimaryKeyRelatedField / OrgScopedPrimaryKeyRelatedField."""

    nested_path: tuple[str, ...] = field(default_factory=tuple)
    """Empty for top-level; ('destination',) for one-level nested."""


def discover_writable_tenant_fks(serializer_cls: type[serializers.Serializer]) -> list[WritableFKField]:
    """Return every writable tenant-FK field on the serializer (top-level + 1 nested)."""
    try:
        instance = _instantiate(serializer_cls)
    except Exception:
        return []

    found: list[WritableFKField] = []
    _walk_fields(instance, nested_path=(), out=found)
    # Stable order — matches `Meta.fields` iteration so test names are deterministic.
    return found


def _instantiate(serializer_cls: type[serializers.Serializer]) -> serializers.Serializer:
    """Build a serializer instance with a minimal context."""
    return serializer_cls(context={"team_id": None, "request": None})


def _walk_fields(
    instance: serializers.Serializer,
    nested_path: tuple[str, ...],
    out: list[WritableFKField],
) -> None:
    fields_dict = _safe_get_fields(instance)
    for field_name, drf_field in fields_dict.items():
        if drf_field.read_only:
            continue
        record = _classify_field(field_name, drf_field, nested_path)
        if record is not None:
            out.append(record)
            continue
        # If this is a nested ModelSerializer (depth-1 only), recurse once.
        if not nested_path and isinstance(drf_field, serializers.ModelSerializer):
            _walk_fields(drf_field, nested_path=(field_name,), out=out)


def _safe_get_fields(instance: serializers.Serializer) -> dict[str, serializers.Field]:
    try:
        # `.fields` triggers field building; some serializers raise during that step
        # if context expectations are unmet. Treat as "no fields discoverable".
        return dict(instance.fields)
    except Exception:
        return {}


def _classify_field(
    field_name: str,
    drf_field: serializers.Field,
    nested_path: tuple[str, ...],
) -> Optional[WritableFKField]:
    if not isinstance(drf_field, serializers.PrimaryKeyRelatedField):
        return None
    target = _resolve_target_model(drf_field)
    if target is None:
        return None
    scope = classify_model_scope(target.__name__)
    if scope is None:
        return None
    return WritableFKField(
        serializer_field_name=field_name,
        source_attr=getattr(drf_field, "source", None) if drf_field.source != field_name else None,
        target_model=target,
        scope=scope,
        is_already_scoped=_is_scoped_field(drf_field),
        nested_path=nested_path,
    )


def _resolve_target_model(drf_field: serializers.PrimaryKeyRelatedField) -> Optional[type[models.Model]]:
    """Find the Django model the PK field points at."""
    qs = getattr(drf_field, "queryset", None)
    if qs is not None:
        model = getattr(qs, "model", None)
        if model is not None:
            return model
    return None


def _is_scoped_field(drf_field: serializers.PrimaryKeyRelatedField) -> bool:
    """True when the field already self-scopes its queryset to the caller's tenant."""
    # Imported here to keep this module importable without Django app loading
    # in `discover_writable_tenant_fks`'s consumers.
    from posthog.api.scoped_related_fields import OrgScopedPrimaryKeyRelatedField, TeamScopedPrimaryKeyRelatedField

    return isinstance(drf_field, (TeamScopedPrimaryKeyRelatedField, OrgScopedPrimaryKeyRelatedField))


def iter_unique_fields(records: Iterable[WritableFKField]) -> list[WritableFKField]:
    """Deduplicate by (serializer_field_name, nested_path); first wins."""
    seen: set[tuple[str, tuple[str, ...]]] = set()
    out: list[WritableFKField] = []
    for r in records:
        key = (r.serializer_field_name, r.nested_path)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out
