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

from django.db import models

from drf_spectacular.generators import EndpointEnumerator
from rest_framework import serializers

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH"})

# `module.Serializer.field` -> why the field stays writable. A `TODO` marks a hole that
# the owning team still has to close; the other entries are fields that the API offers
# to clients on purpose.
ALLOWED_WRITABLE: dict[str, str] = {
    "posthog.api.advanced_activity_logs.viewset.ActivityLogSerializer.created_at": "TODO: server-owned audit timestamp, make read-only",
    "posthog.api.event_definition.EventDefinitionSerializer.created_at": "TODO: server-owned, set when ingestion first sees the event",
    "posthog.api.event_definition.EventDefinitionSerializer.last_seen_at": "TODO: server-owned ingestion telemetry, make read-only",
    "posthog.api.web_experiment.WebExperimentsAPISerializer.created_at": "TODO: server-owned creation timestamp, make read-only",
    "products.actions.backend.api.action.ActionSerializer.last_calculated_at": "TODO: server-owned, written by the action calculation job",
    "products.actions.backend.api.action.ActionSerializer.pinned_at": "Clients pin an action by writing a timestamp and unpin it by writing null",
    "products.batch_exports.backend.api.batch_export.BatchExportSerializer.start_at": "Client-supplied bound, runs before it are not triggered",
    "products.batch_exports.backend.api.batch_export.BatchExportSerializer.end_at": "Client-supplied bound, runs after it are not triggered",
    "products.batch_exports.backend.api.batch_export.BatchExportSerializer.last_paused_at": "TODO: written by the pause action, make read-only",
}


def _write_exposed_serializers() -> list[type[serializers.ModelSerializer]]:
    """Every `ModelSerializer` that a route with a write method uses.

    `EndpointEnumerator` is what drf-spectacular walks the URL conf with to build the
    OpenAPI schema, so this sees the same routes as `/api/schema/`, including the
    routes that products register themselves.
    """
    found: dict[type[serializers.ModelSerializer], None] = {}
    for _path, _path_regex, method, callback in EndpointEnumerator().get_api_endpoints():
        if method not in WRITE_METHODS:
            continue
        serializer_class = getattr(getattr(callback, "cls", None), "serializer_class", None)
        if isinstance(serializer_class, type) and issubclass(serializer_class, serializers.ModelSerializer):
            found[serializer_class] = None
    return list(found)


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


def collect_violations() -> dict[str, str]:
    """Writable server-owned timestamps, keyed by `module.Serializer.field`."""
    violations: dict[str, str] = {}
    for serializer_class in _write_exposed_serializers():
        model = getattr(getattr(serializer_class, "Meta", None), "model", None)
        if model is None:
            continue
        try:
            fields = serializer_class().fields
        except Exception:
            # A serializer that needs constructor arguments or context cannot be inspected
            # here. The guard is a ratchet over what it can read, not a proof over the API.
            continue
        for name, field in fields.items():
            if not isinstance(field, serializers.DateTimeField) or field.read_only:
                continue
            try:
                model_field = model._meta.get_field(field.source or name)
            except Exception:
                continue
            if not isinstance(model_field, models.DateTimeField):
                continue
            reasons = _self_filling_reasons(model_field)
            if reasons:
                key = f"{serializer_class.__module__}.{serializer_class.__name__}.{name}"
                violations[key] = ", ".join(reasons)
    return violations


def test_server_owned_timestamps_are_read_only() -> None:
    violations = collect_violations()
    unexpected = sorted(f"{key} ({reasons})" for key, reasons in violations.items() if key not in ALLOWED_WRITABLE)
    assert not unexpected, (
        "These serializers let a client write a timestamp that the model fills in itself. "
        "Add the field to read_only_fields on Meta, or declare it with read_only=True. "
        "If a client is supposed to set it, add it to ALLOWED_WRITABLE in "
        "posthog/test/repo_invariants/test_serializer_timestamp_guard.py with a one-line reason:\n"
        + "\n".join(unexpected)
    )


def test_allowlist_has_no_stale_entries() -> None:
    stale = sorted(set(ALLOWED_WRITABLE) - set(collect_violations()))
    assert not stale, (
        "These ALLOWED_WRITABLE entries no longer match a writable timestamp. Remove them so "
        "the allowlist keeps shrinking:\n" + "\n".join(stale)
    )
