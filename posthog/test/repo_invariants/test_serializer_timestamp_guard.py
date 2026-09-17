"""Guard against writable server-owned timestamps on API serializers.

A serializer that a write route (POST, PUT or PATCH) uses must not expose a
`DateTimeField` for writing when the backend owns the value. The route then lets a
client overwrite something the product reads back as server truth.
`FeatureFlagSerializer` carried that hole on `created_at` and `last_called_at` for
years, because a `ModelSerializer` builds every concrete column as writable unless
something says otherwise.

Django has no declarative marker for "the server owns this column", so ownership is
read from two kinds of evidence:

- the column fills itself in (`auto_now`, `auto_now_add`, or a non-null `default`), or
- the column is named the way audit and telemetry columns are named (`created_at`,
  `last_called_at`, `last_seen_at`, ...), which is the only signal a plain nullable
  column that only the backend writes ever gives.

A bare `default=None` is not evidence: it means nullable, not server-filled, and
flagging it caught fields a client is supposed to set (a batch export's `start_at`).

To clear a violation on a field the serializer generates from the model, put it in
`read_only_fields` on `Meta`. A field the serializer declares needs `read_only=True`
on the declaration itself, because DRF ignores `read_only_fields` for a declared
field. A timestamp a client is genuinely supposed to set goes in `ALLOWED_WRITABLE`
with a one-line reason.

The failure message lists every violation:

    pytest posthog/test/repo_invariants/test_serializer_timestamp_guard.py
"""

import re
import ast
import sys
import inspect
import textwrap
import functools
import importlib
from collections.abc import Sequence
from typing import Any, TypeGuard

from django.core.exceptions import FieldDoesNotExist
from django.db import models

from rest_framework import serializers
from rest_framework.generics import GenericAPIView

# DRF's enumerator, not the drf-spectacular subclass, because the subclass runs
# `preprocess_exclude_path_format`, which drops every INTERNAL and undocumented route
# from the schema. Those routes still accept writes, so the guard has to see them.
from rest_framework.schemas.generators import EndpointEnumerator

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH"})

# Columns the backend writes on the user's behalf. Matching one is evidence of server
# ownership on its own, because a plain nullable audit column carries no other signal.
SERVER_OWNED_NAME = re.compile(
    r"^(created_at|updated_at|modified_at|deleted_at"
    r"|last_\w+_at"
    r"|\w+_(seen|synced|calculated|refreshed|computed)_at)$"
)

# `module.Serializer.field` -> why a client is allowed to write this timestamp. A `TODO`
# marks a hole the owning team still has to close.
ALLOWED_WRITABLE: dict[str, str] = {
    "ee.clickhouse.views.groups.GroupTypeSerializer.created_at": "TODO: server-owned, the model sets it on creation itself",
    "posthog.api.advanced_activity_logs.viewset.ActivityLogSerializer.created_at": "TODO: server-owned audit timestamp, make read-only",
    "posthog.api.advanced_activity_logs.viewset.ActivityLogFlatExportSerializer.created_at": "TODO: server-owned audit timestamp, make read-only",
    "posthog.api.event_definition.EventDefinitionSerializer.created_at": "TODO: server-owned, set when ingestion first sees the event",
    "posthog.api.event_definition.EventDefinitionSerializer.last_seen_at": "TODO: server-owned ingestion telemetry, make read-only",
    "posthog.api.my_notifications.MyNotificationsSerializer.created_at": "TODO: server-owned activity log timestamp, make read-only",
    "posthog.api.web_experiment.WebExperimentsAPISerializer.created_at": "TODO: server-owned creation timestamp, make read-only",
    "products.actions.backend.api.action.ActionSerializer.last_calculated_at": "TODO: server-owned, written by the action calculation job",
    "products.batch_exports.backend.api.batch_export.BatchExportSerializer.last_paused_at": "TODO: written by the pause action, make read-only",
    "products.dashboards.backend.api.dashboard.DashboardSerializer.last_accessed_at": "TODO: server-owned, written when a dashboard is opened",
    "products.product_analytics.backend.presentation.insight.InsightBasicSerializer.last_modified_at": "TODO: server-owned, written on each save",
}

# Views and serializers the guard cannot read, each with a reason. An entry hides part
# of a write route, so this stays empty unless something genuinely cannot be resolved.
UNCHECKED: dict[str, str] = {}

# Serializers that only dynamic selection reaches. They are the regressions this file
# exists to prevent, so discovery is asserted to still find them.
HARD_TO_DISCOVER = {
    "products.product_analytics.backend.presentation.insight.MCPInsightSerializer": (
        "chosen by get_serializer_class only when the x-posthog-client request header is mcp"
    ),
    "ee.api.ee_event_definition.EnterpriseEventDefinitionSerializer": (
        "assigned to a local inside get_serializer_class from an import made in the function body"
    ),
}


def _dotted_name(obj: type) -> str:
    return f"{obj.__module__}.{obj.__qualname__}"


def _is_serializer(obj: Any) -> TypeGuard[type[serializers.BaseSerializer]]:
    return isinstance(obj, type) and issubclass(obj, serializers.BaseSerializer)


def _resolve(expression: ast.expr, scope: dict[str, Any], view_class: type) -> list[Any]:
    """Every object an expression in a `get_serializer_class` body could evaluate to."""
    match expression:
        case ast.IfExp(body=body, orelse=orelse):
            return _resolve(body, scope, view_class) + _resolve(orelse, scope, view_class)
        case ast.BoolOp(values=values):
            return [found for value in values for found in _resolve(value, scope, view_class)]
        case ast.Name(id=name):
            return [scope[name]] if name in scope else []
        case ast.Attribute():
            attributes: list[str] = []
            node: ast.expr = expression
            while isinstance(node, ast.Attribute):
                attributes.append(node.attr)
                node = node.value
            if not isinstance(node, ast.Name):
                return []
            # `self.x.y` walks the class, anything else walks an imported module.
            found = view_class if node.id == "self" else scope.get(node.id)
            for attribute in reversed(attributes):
                found = getattr(found, attribute, None)
            return [found] if found is not None else []
        case ast.Subscript(value=value):
            return [
                entry
                for mapping in _resolve(value, scope, view_class)
                if isinstance(mapping, dict)
                for entry in mapping.values()
            ]
        case ast.Call(func=ast.Attribute(value=value, attr="get"), args=args):
            # A `serializer_classes.get(self.action, default)` lookup table.
            resolved = [
                entry
                for mapping in _resolve(value, scope, view_class)
                if isinstance(mapping, dict)
                for entry in mapping.values()
            ]
            return resolved + [found for argument in args for found in _resolve(argument, scope, view_class)]
        case _:
            return []


def _function_scope(tree: ast.AST, scope: dict[str, Any], view_class: type) -> tuple[dict[str, Any], set[type]]:
    """Names bound inside the function body: deferred imports and local assignments.

    The serializers bound here are returned separately from the scope, because the
    scope also carries the defining module's globals, and every serializer that module
    happens to import is not a serializer this view can hand to a request.
    """
    scope = dict(scope)
    bound: set[type] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            try:
                module = importlib.import_module(node.module)
            except Exception:
                continue
            for alias in node.names:
                imported = getattr(module, alias.name, None)
                if imported is not None:
                    scope[alias.asname or alias.name] = imported
                    if _is_serializer(imported):
                        bound.add(imported)
    for node in ast.walk(tree):
        targets: Sequence[ast.expr]
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        assigned = [found for found in _resolve(value, scope, view_class) if _is_serializer(found)]
        bound.update(assigned)
        for target in targets:
            if isinstance(target, ast.Name) and assigned:
                scope[target.id] = assigned[0]
    return scope, bound


def _serializer_choices(view_class: type) -> tuple[set[type], list[str]]:
    """Every serializer a view could hand to a write request, and what would not resolve.

    `get_serializer_class` is read statically rather than called, because calling it
    returns the one serializer that matches a synthesized request: a view that branches
    on a header or on request data would show the guard a single arm and hide the rest.
    """
    found: set[type] = set()
    unresolved: list[str] = []
    declared = getattr(view_class, "serializer_class", None)
    if _is_serializer(declared):
        found.add(declared)
    for attribute in vars(view_class).values():
        if isinstance(attribute, dict):
            found.update(entry for entry in attribute.values() if _is_serializer(entry))
    for klass in view_class.__mro__:
        function = vars(klass).get("get_serializer_class")
        if function is None or klass is GenericAPIView:
            continue
        try:
            tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
        except Exception as error:
            unresolved.append(f"{klass.__qualname__}.get_serializer_class: {type(error).__name__}")
            continue
        module_scope = vars(sys.modules.get(function.__module__, None)) or {}
        scope, locally_bound = _function_scope(tree, module_scope, view_class)
        found.update(locally_bound)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Return) or node.value is None:
                continue
            resolved = _resolve(node.value, scope, view_class)
            serializer_classes = [entry for entry in resolved if _is_serializer(entry)]
            if serializer_classes:
                found.update(serializer_classes)
            elif not resolved and not isinstance(node.value, ast.Call):
                unresolved.append(f"{klass.__qualname__}.get_serializer_class -> {ast.unparse(node.value)[:60]}")
    return found, unresolved


def _request_body_serializers(view_class: type, handler_names: set[str]) -> set[type]:
    """Serializers an `@extend_schema(request=...)` decorator names on a write handler."""
    found: set[type] = set()
    for name in handler_names:
        annotation = getattr(getattr(view_class, name, None), "_spectacular_annotation", None) or {}
        declared = annotation.get("request")
        if _is_serializer(declared):
            found.add(declared)
        elif isinstance(declared, dict):
            found.update(entry for entry in declared.values() if _is_serializer(entry))
    return found


def _write_exposed_serializers() -> tuple[set[type], dict[str, str]]:
    """Every serializer reachable from a write route, and everything that would not resolve."""
    found: set[type] = set()
    unresolved: dict[str, str] = {}
    for _path, method, callback in EndpointEnumerator().get_api_endpoints():
        view_class = getattr(callback, "cls", None)
        if method not in WRITE_METHODS or view_class is None:
            continue
        choices, problems = _serializer_choices(view_class)
        found.update(choices)
        if problems:
            unresolved[_dotted_name(view_class)] = "; ".join(problems)
        # A viewset routes the method to an action; a plain APIView handles it by name.
        actions = getattr(callback, "actions", None) or {}
        handler_names = {method.lower(), actions.get(method.lower())}
        found.update(_request_body_serializers(view_class, {name for name in handler_names if name}))
    return found, unresolved


def _server_owned_reasons(model_field: models.DateTimeField) -> list[str]:
    """The evidence that the backend, not the client, owns this column."""
    return [
        name
        for name, present in (
            ("auto_now", model_field.auto_now),
            ("auto_now_add", model_field.auto_now_add),
            ("non-null default", model_field.has_default() and model_field.get_default() is not None),
            ("server-owned name", bool(SERVER_OWNED_NAME.match(model_field.name))),
        )
        if present
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
            reasons = _server_owned_reasons(model_field)
            if reasons:
                violations[f"{_dotted_name(serializer_class)}.{name}"] = ", ".join(reasons)
    return violations, problems


def test_server_owned_timestamps_are_read_only() -> None:
    violations, _ = collect_violations()
    unexpected = sorted(f"{key} ({reasons})" for key, reasons in violations.items() if key not in ALLOWED_WRITABLE)
    assert not unexpected, (
        "These serializers let a client write a timestamp the backend owns. "
        "Add a generated field to read_only_fields on Meta; a field the serializer declares "
        "needs read_only=True on the declaration, because read_only_fields does not reach it. "
        "If a client is supposed to set it, add it to ALLOWED_WRITABLE in "
        "posthog/test/repo_invariants/test_serializer_timestamp_guard.py with a one-line reason:\n"
        + "\n".join(unexpected)
    )


def test_every_write_route_can_be_checked() -> None:
    _, problems = collect_violations()
    unexpected = sorted(f"{key} ({error})" for key, error in problems.items() if key not in UNCHECKED)
    assert not unexpected, (
        "The guard could not read these, so their write routes go unchecked. Make the view or "
        "serializer resolvable without a request, or add it to UNCHECKED in "
        "posthog/test/repo_invariants/test_serializer_timestamp_guard.py with a one-line reason:\n"
        + "\n".join(unexpected)
    )


def test_discovery_reaches_dynamically_selected_serializers() -> None:
    discovered = {_dotted_name(serializer) for serializer in _write_exposed_serializers()[0]}
    missing = sorted(f"{name} ({why})" for name, why in HARD_TO_DISCOVER.items() if name not in discovered)
    assert not missing, (
        "Discovery no longer reaches these serializers, so a server-owned timestamp on one of them "
        "would pass the sweep above. Reading get_serializer_class statically is what finds them:\n" + "\n".join(missing)
    )


def test_nullable_column_without_a_default_is_owned_by_its_name() -> None:
    # FeatureFlag.last_called_at declares no auto_now, auto_now_add or default, so the
    # naming convention is the only thing that makes it server-owned.
    field: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    field.name = "last_called_at"
    assert _server_owned_reasons(field) == ["server-owned name"]


def test_bare_null_default_is_not_evidence_of_server_ownership() -> None:
    # A batch export's start_at is declared this way and a client is supposed to set it.
    field: models.DateTimeField = models.DateTimeField(null=True, default=None)
    field.name = "start_at"
    assert _server_owned_reasons(field) == []
