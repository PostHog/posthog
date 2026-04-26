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
  - **Implicit string-id fields on a ModelSerializer**:
    `dashboard_id = IntegerField()` / `UUIDField()` / `CharField()`.
    We resolve the target by stripping the `_id` suffix and looking
    up the corresponding Django ForeignKey on `Meta.model`.
  - **Name-pattern fields on any Serializer (including non-Model)**:
    `<thing>_id` IntegerField/UUIDField/CharField where `<thing>`
    matches a tenant-scoped model name in the semgrep allowlist via
    case-insensitive partial match (`template` → `DashboardTemplate`,
    `source_template` → `DashboardTemplate`). Catches IDORs on custom
    `serializers.Serializer` action body shapes.
  - **One level of nested serializer fields**. The common BatchExport-
    style "destination.id" case is depth 1; deeper nesting is rare.

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

from posthog.test.idor.fk_target_models import classify_model_scope, lookup_tenant_models_by_partial_name

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

    is_many: bool = False
    """True if the field is a ManyRelatedField (PrimaryKeyRelatedField with many=True)."""

    is_name_pattern: bool = False
    """True if discovered via name-pattern matching against the semgrep allowlist
    (works on any Serializer, not just ModelSerializer with a matching ForeignKey)."""


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
        records = _classify_field(field_name, drf_field, nested_path, serializer_model)
        if records:
            out.extend(records)
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
) -> list[WritableFKField]:
    if isinstance(drf_field, serializers.ManyRelatedField):
        record = _classify_many_related(field_name, drf_field, nested_path)
        return [record] if record else []
    if isinstance(drf_field, serializers.PrimaryKeyRelatedField):
        record = _classify_explicit_fk(field_name, drf_field, nested_path)
        return [record] if record else []
    record = _classify_implicit_id(field_name, drf_field, nested_path, serializer_model)
    if record is not None:
        return [record]
    # Fallback: name-pattern match against the tenant-scoped allowlist.
    # Works on any Serializer (including non-Model), so it catches custom
    # action body serializers like CopyDashboardTemplateSerializer. The
    # match may be ambiguous (e.g. `template` → DashboardTemplate /
    # MessageTemplate / HogFlowTemplate); we emit one record per match.
    return _classify_name_pattern_id(field_name, drf_field, nested_path)


def _classify_many_related(
    field_name: str,
    drf_field: serializers.ManyRelatedField,
    nested_path: tuple[str, ...],
) -> Optional[WritableFKField]:
    """Detect `PrimaryKeyRelatedField(many=True)`, surfaced by DRF as ManyRelatedField.

    The wrapping ManyRelatedField doesn't carry a queryset; the underlying
    `child_relation` is a single-item PK field with the queryset and any
    scoped subclass. We reuse the explicit-FK classifier and stamp the
    `is_many` flag.
    """
    child = drf_field.child_relation
    if not isinstance(child, serializers.PrimaryKeyRelatedField):
        return None
    record = _classify_explicit_fk(field_name, child, nested_path)
    if record is None:
        return None
    # `replace` avoids re-implementing all the field copy-construction.
    return WritableFKField(
        serializer_field_name=record.serializer_field_name,
        source_attr=record.source_attr,
        target_model=record.target_model,
        scope=record.scope,
        is_already_scoped=record.is_already_scoped,
        nested_path=record.nested_path,
        is_implicit=record.is_implicit,
        is_many=True,
    )


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


# Prefixes commonly used to qualify the role of an FK reference (e.g.
# `source_template_id` is still a `template`). Strip them before
# attempting to resolve the model name.
_ROLE_PREFIXES = ("source_", "target_", "from_", "to_", "new_", "old_", "parent_", "child_")


def _classify_name_pattern_id(
    field_name: str,
    drf_field: serializers.Field,
    nested_path: tuple[str, ...],
) -> list[WritableFKField]:
    """Catch `<thing>_id` fields where the serializer has no Meta.model to consult.

    The tom/dashboard-template shape: a `serializers.Serializer` subclass
    (used as an @action's request body) declares `source_template_id =
    UUIDField(...)`. Without `Meta.model._meta.get_field('template')` to
    consult, we fall back to mapping the snake_cased `<thing>` to tenant-
    scoped model names in the semgrep allowlist.

    `<thing>` may match multiple models (e.g. `template` matches three);
    we emit one record per match. The runtime test fans out across them.
    """
    if not isinstance(drf_field, _IMPLICIT_FK_FIELD_TYPES):
        return []
    if not field_name.endswith("_id") or field_name == "_id":
        return []
    thing = field_name[:-3]
    for prefix in _ROLE_PREFIXES:
        if thing.startswith(prefix):
            thing = thing[len(prefix) :]
            break
    candidate_names = lookup_tenant_models_by_partial_name(thing)
    if not candidate_names:
        return []
    out: list[WritableFKField] = []
    source_attr = getattr(drf_field, "source", None)
    if source_attr == field_name:
        source_attr = None
    for class_name in candidate_names:
        target = _resolve_django_model_by_name(class_name)
        if target is None:
            continue
        scope = classify_model_scope(target.__name__)
        if scope is None:
            continue
        out.append(
            WritableFKField(
                serializer_field_name=field_name,
                source_attr=source_attr,
                target_model=target,
                scope=scope,
                is_already_scoped=False,
                nested_path=nested_path,
                is_implicit=True,
                is_name_pattern=True,
            )
        )
    return out


def _resolve_django_model_by_name(class_name: str) -> Optional[type[models.Model]]:
    """Look up a Django model class by its `__name__` across all installed apps.

    The semgrep allowlist gives us a model name string; to drive
    `build_minimal_instance` and friends we need the actual class. Walk
    `django.apps.apps.get_models()` and return the first match. Multiple
    apps with same model name return None (ambiguous).
    """
    from django.apps import apps

    matches = [m for m in apps.get_models() if m.__name__ == class_name]
    if len(matches) == 1:
        return matches[0]
    return None


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


@dataclass(frozen=True)
class ActionSerializerCase:
    """A custom @action endpoint with its request serializer."""

    method_name: str
    """The bound method name on the viewset (e.g. `copy_between_projects`)."""

    url_path: str
    """URL segment after the resource list, defaults to the method name."""

    http_methods: tuple[str, ...]
    """HTTP methods the action accepts (uppercased)."""

    detail: bool
    """True if the action is a detail-route (operates on a single instance)."""

    serializer_cls: type[serializers.Serializer]
    """Request body serializer (extracted from `@extend_schema(request=...)`)."""


def discover_action_serializers(viewset_cls: type) -> list[ActionSerializerCase]:
    """Walk a viewset's @action methods and pull their request serializers.

    `@extend_schema(request=Serializer)` (drf-spectacular) wraps the action's
    schema class. The `request` value is captured in a closure inside
    `get_request_serializer`; we read it via `__closure__` introspection
    rather than calling the method (which requires runtime view context).
    """
    if not hasattr(viewset_cls, "get_extra_actions"):
        return []
    out: list[ActionSerializerCase] = []
    for action_method in viewset_cls.get_extra_actions():
        schema_cls = (action_method.kwargs or {}).get("schema")
        if schema_cls is None:
            continue
        request_serializer = _extract_extend_schema_request(schema_cls)
        if request_serializer is None:
            continue
        if not isinstance(request_serializer, type):
            continue
        if not issubclass(request_serializer, serializers.Serializer):
            continue
        # @action's mapping={method.lower(): method_name} is the source of
        # truth for which HTTP methods this action accepts.
        mapping = getattr(action_method, "mapping", None) or {}
        methods = tuple(m.upper() for m in mapping.keys()) or ("GET",)
        url_path = getattr(action_method, "url_path", None) or action_method.__name__
        detail = bool(getattr(action_method, "detail", False))
        out.append(
            ActionSerializerCase(
                method_name=action_method.__name__,
                url_path=url_path,
                http_methods=methods,
                detail=detail,
                serializer_cls=request_serializer,
            )
        )
    return out


def _extract_extend_schema_request(schema_cls: type) -> Optional[type]:
    """Pull the captured `request=` value from drf-spectacular's @extend_schema closure.

    drf-spectacular wraps each @extend_schema invocation as an `ExtendedSchema`
    subclass in the MRO. The kwargs (including `request`) live in the
    `get_request_serializer` method's closure freevars. Walk the MRO and
    return the first non-empty `request` capture.
    """
    from rest_framework.fields import empty

    for klass in schema_cls.__mro__:
        if klass.__name__ != "ExtendedSchema":
            continue
        method = klass.__dict__.get("get_request_serializer")
        if method is None or method.__closure__ is None:
            continue
        for freevar_name, cell in zip(method.__code__.co_freevars, method.__closure__):
            if freevar_name != "request":
                continue
            value = cell.cell_contents
            if value is empty or value is None:
                continue
            return value
    return None
