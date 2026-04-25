"""
Discover writable tenant-FK serializer fields.

Walks a DRF `ModelSerializer` (or generic `Serializer`) and emits one
`WritableFKField` per writable FK reference whose target is tenant-
scoped per the semgrep allowlist. The emitted records drive the
parametric `test_cross_tenant_fk_in_patch` test.

What we detect:

  - **Explicit PK fields**: `serializers.PrimaryKeyRelatedField(...)` —
    the canonical shape, including `TeamScopedPrimaryKeyRelatedField`
    subclasses (defense in depth).
  - **Implicit string-id fields**: `dashboard_id = IntegerField()` /
    `UUIDField()` / `CharField()` — common in older serializers that
    accept the FK as a raw scalar plus a hand-rolled `validate()`.
    We resolve the target by stripping the `_id` suffix and looking
    up the corresponding Django ForeignKey on `Meta.model`.
  - **One level of nested serializer fields**. The common BatchExport-
    style "destination.id" case is depth 1; deeper nesting is rare
    (Phase 5c follow-up).

Boundaries:

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

    is_implicit: bool = False
    """True if discovered via the string-id naming pattern rather than an explicit PrimaryKeyRelatedField."""


# DRF field types that can carry a raw FK pk in the string-id naming pattern.
_IMPLICIT_FK_FIELD_TYPES = (
    serializers.IntegerField,
    serializers.UUIDField,
    serializers.CharField,
)


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
    serializer_model = _serializer_meta_model(instance)
    fields_dict = _safe_get_fields(instance)
    for field_name, drf_field in fields_dict.items():
        if drf_field.read_only:
            continue
        record = _classify_field(field_name, drf_field, nested_path, serializer_model)
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


def _serializer_meta_model(instance: serializers.Serializer) -> Optional[type[models.Model]]:
    meta = getattr(type(instance), "Meta", None)
    if meta is None:
        return None
    return getattr(meta, "model", None)


def _classify_field(
    field_name: str,
    drf_field: serializers.Field,
    nested_path: tuple[str, ...],
    serializer_model: Optional[type[models.Model]],
) -> Optional[WritableFKField]:
    if isinstance(drf_field, serializers.PrimaryKeyRelatedField):
        return _classify_explicit_fk(field_name, drf_field, nested_path)
    return _classify_implicit_id(field_name, drf_field, nested_path, serializer_model)


def _classify_explicit_fk(
    field_name: str,
    drf_field: serializers.PrimaryKeyRelatedField,
    nested_path: tuple[str, ...],
) -> Optional[WritableFKField]:
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


def _classify_implicit_id(
    field_name: str,
    drf_field: serializers.Field,
    nested_path: tuple[str, ...],
    serializer_model: Optional[type[models.Model]],
) -> Optional[WritableFKField]:
    """Catch the `<thing>_id = IntegerField()` / `UUIDField()` / `CharField()` pattern.

    Many serializers accept an FK as a raw scalar with a hand-rolled
    `validate()`. The naming pattern + a corresponding `ForeignKey` on
    the model lets us still recognize the field as an FK reference.
    """
    if serializer_model is None:
        return None
    if not isinstance(drf_field, _IMPLICIT_FK_FIELD_TYPES):
        return None
    if not field_name.endswith("_id"):
        return None
    related_attr = field_name[:-3]
    target = _resolve_implicit_target_model(serializer_model, drf_field, related_attr)
    if target is None:
        return None
    scope = classify_model_scope(target.__name__)
    if scope is None:
        return None
    source_attr = getattr(drf_field, "source", None)
    if source_attr == field_name:
        source_attr = None
    return WritableFKField(
        serializer_field_name=field_name,
        source_attr=source_attr,
        target_model=target,
        scope=scope,
        # By construction the field is a raw scalar with no queryset
        # filtering — there's no way it scopes itself to the tenant.
        is_already_scoped=False,
        nested_path=nested_path,
        is_implicit=True,
    )


def _resolve_implicit_target_model(
    serializer_model: type[models.Model],
    drf_field: serializers.Field,
    related_attr: str,
) -> Optional[type[models.Model]]:
    """Look up the FK target by stripping `_id` and inspecting the model.

    `source=` overrides take precedence — if the serializer field is
    `dashboard_id` but `source=dashboard`, we look up `dashboard`.
    """
    candidate_names = []
    source_attr = getattr(drf_field, "source", None)
    if source_attr and source_attr != drf_field.field_name:  # type: ignore[attr-defined]
        candidate_names.append(source_attr.removesuffix("_id"))
    candidate_names.append(related_attr)
    for name in candidate_names:
        try:
            model_field = serializer_model._meta.get_field(name)
        except Exception:
            continue
        if isinstance(model_field, models.ForeignKey):
            related = model_field.related_model
            if isinstance(related, type) and issubclass(related, models.Model):
                return related
    return None


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
