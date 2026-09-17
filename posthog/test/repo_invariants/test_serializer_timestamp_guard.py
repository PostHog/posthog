"""Guard against writable server-owned timestamps on API serializers.

A `ModelSerializer` that a write route (POST, PUT or PATCH) uses must not expose a
`DateTimeField` for writing when the model column fills itself in, which is the case
for `auto_now`, `auto_now_add` and a `default`. The route then lets a client write a
value that the product reads back as server truth. `FeatureFlagSerializer` carried
that hole on `created_at` and `last_called_at` for years, because a `ModelSerializer`
builds every concrete column as writable unless something says otherwise.

To clear a violation, put the field in `read_only_fields` on `Meta`, or declare it
with `read_only=True`. A field that a client is supposed to set goes in
`ALLOWED_WRITABLE` with a one-line reason.

The failure message lists every violation:

    pytest posthog/test/repo_invariants/test_serializer_timestamp_guard.py
"""

import functools
from typing import Any

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.test import RequestFactory

from rest_framework import serializers
from rest_framework.generics import GenericAPIView
from rest_framework.request import Request

# DRF's enumerator, not the drf-spectacular subclass, because the subclass runs
# `preprocess_exclude_path_format`, which drops every INTERNAL and undocumented route
# from the schema. Those routes still accept writes, so the guard has to see them.
from rest_framework.schemas.generators import EndpointEnumerator

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH"})

# `module.Serializer.field` -> why the field stays writable. A `TODO` marks a hole that
# the owning team still has to close; the other entries are fields that the API offers
# to clients on purpose.
ALLOWED_WRITABLE: dict[str, str] = {
    "posthog.api.advanced_activity_logs.viewset.ActivityLogSerializer.created_at": "TODO: server-owned audit timestamp, make read-only",
    "posthog.api.event_definition.EventDefinitionSerializer.created_at": "TODO: server-owned, set when ingestion first sees the event",
    "posthog.api.event_definition.EventDefinitionSerializer.last_seen_at": "TODO: server-owned ingestion telemetry, make read-only",
    "posthog.api.my_notifications.MyNotificationsSerializer.created_at": "TODO: server-owned activity log timestamp, make read-only",
    "posthog.api.web_experiment.WebExperimentsAPISerializer.created_at": "TODO: server-owned creation timestamp, make read-only",
    "products.actions.backend.api.action.ActionSerializer.last_calculated_at": "TODO: server-owned, written by the action calculation job",
    "products.actions.backend.api.action.ActionSerializer.pinned_at": "Clients pin an action by writing a timestamp and unpin it by writing null",
    "products.batch_exports.backend.api.batch_export.BatchExportSerializer.start_at": "Client-supplied bound, runs before it are not triggered",
    "products.batch_exports.backend.api.batch_export.BatchExportSerializer.end_at": "Client-supplied bound, runs after it are not triggered",
    "products.batch_exports.backend.api.batch_export.BatchExportSerializer.last_paused_at": "TODO: written by the pause action, make read-only",
}

# Views whose serializer choice this file cannot resolve, and serializers it cannot
# build fields for. Each entry hides part of a write route from the guard, so an entry
# needs a reason and the list has to stay short.
UNCHECKED: dict[str, str] = {
    "products.managed_migrations.backend.api.batch_imports.BatchImportViewSet": "get_serializer_class branches on request.data, which needs a real upload request; the static serializer_class is still checked",
}


def _dotted_name(obj: type) -> str:
    return f"{obj.__module__}.{obj.__qualname__}"


def _declared_request_serializer(view_class: type, action: str) -> Any:
    """The serializer an `@extend_schema(request=...)` decorator names on the action."""
    annotation = getattr(getattr(view_class, action, None), "_spectacular_annotation", None) or {}
    return annotation.get("request")


def _selected_serializer(view_class: type, callback: Any, method: str, action: str) -> Any:
    """The serializer `get_serializer_class()` picks for this action.

    A viewset that serves a different serializer per action, either through an override
    or through a request-schema decorator, would otherwise show the guard only its
    response serializer. The view runs against a throwaway request, so an override that
    reads the request still resolves.
    """
    override = getattr(view_class, "get_serializer_class", None)
    if override is None or override is GenericAPIView.get_serializer_class:
        return None
    view = view_class(**(getattr(callback, "initkwargs", None) or {}))
    view.action = action
    view.kwargs = {}
    view.format_kwarg = None
    view.request = Request(getattr(RequestFactory(), method.lower())("/", data="{}", content_type="application/json"))
    return view.get_serializer_class()


def _write_exposed_serializers() -> tuple[set[type], dict[str, str]]:
    """Every serializer a write route uses, plus the views that would not resolve."""
    found: set[type] = set()
    unresolved: dict[str, str] = {}
    for _path, method, callback in EndpointEnumerator().get_api_endpoints():
        view_class = getattr(callback, "cls", None)
        if method not in WRITE_METHODS or view_class is None:
            continue
        candidates = [getattr(view_class, "serializer_class", None)]
        action = (getattr(callback, "actions", None) or {}).get(method.lower())
        if action:
            candidates.append(_declared_request_serializer(view_class, action))
            try:
                candidates.append(_selected_serializer(view_class, callback, method, action))
            except Exception as error:
                unresolved[_dotted_name(view_class)] = f"{type(error).__name__}: {error}"
        found.update(
            candidate
            for candidate in candidates
            if isinstance(candidate, type) and issubclass(candidate, serializers.ModelSerializer)
        )
    return found, unresolved


def _self_filling_reasons(model_field: models.DateTimeField) -> list[str]:
    """The declarations that make the database column fill itself in.

    `default=None` counts. The column carries no server value of its own, but a
    nullable timestamp that only the backend writes reads the same way to a client,
    so the guard asks for a reason either way.
    """
    return [
        name
        for name, declared in (
            ("auto_now", model_field.auto_now),
            ("auto_now_add", model_field.auto_now_add),
            ("default", model_field.has_default()),
        )
        if declared
    ]


@functools.cache
def collect_violations() -> tuple[dict[str, str], dict[str, str]]:
    """Writable server-owned timestamps, and everything the guard could not read.

    The first mapping is keyed by `module.Serializer.field`, the second by the dotted
    name of the view or serializer that failed, and both values say why.
    """
    violations: dict[str, str] = {}
    serializer_classes, problems = _write_exposed_serializers()
    for serializer_class in serializer_classes:
        model = getattr(getattr(serializer_class, "Meta", None), "model", None)
        if model is None:
            continue
        try:
            fields = serializer_class().fields
        except Exception as error:
            problems[_dotted_name(serializer_class)] = f"{type(error).__name__}: {error}"
            continue
        for name, field in fields.items():
            if not isinstance(field, serializers.DateTimeField) or field.read_only:
                continue
            try:
                model_field = model._meta.get_field(field.source or name)
            except FieldDoesNotExist:
                continue
            if not isinstance(model_field, models.DateTimeField):
                continue
            reasons = _self_filling_reasons(model_field)
            if reasons:
                violations[f"{_dotted_name(serializer_class)}.{name}"] = ", ".join(reasons)
    return violations, problems


def test_server_owned_timestamps_are_read_only() -> None:
    violations, _ = collect_violations()
    unexpected = sorted(f"{key} ({reasons})" for key, reasons in violations.items() if key not in ALLOWED_WRITABLE)
    assert not unexpected, (
        "These serializers let a client write a timestamp that the model fills in itself. "
        "Add the field to read_only_fields on Meta, or declare it with read_only=True. "
        "If a client is supposed to set it, add it to ALLOWED_WRITABLE in "
        "posthog/test/repo_invariants/test_serializer_timestamp_guard.py with a one-line reason:\n"
        + "\n".join(unexpected)
    )


def test_every_write_route_can_be_checked() -> None:
    _, problems = collect_violations()
    unexpected = sorted(f"{key} ({error})" for key, error in problems.items() if key not in UNCHECKED)
    assert not unexpected, (
        "The guard could not read these, so their write routes go unchecked. Make the view or "
        "serializer resolvable without a real request, or add it to UNCHECKED in "
        "posthog/test/repo_invariants/test_serializer_timestamp_guard.py with a one-line reason:\n"
        + "\n".join(unexpected)
    )


def test_allowlists_have_no_stale_entries() -> None:
    violations, problems = collect_violations()
    stale = sorted((set(ALLOWED_WRITABLE) - set(violations)) | (set(UNCHECKED) - set(problems)))
    assert not stale, (
        "These ALLOWED_WRITABLE or UNCHECKED entries no longer match anything. Remove them so "
        "the allowlists keep shrinking:\n" + "\n".join(stale)
    )
