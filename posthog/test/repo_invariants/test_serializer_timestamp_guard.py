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

from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers, viewsets
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


def _action_literals(test: ast.expr) -> set[str] | None:
    """The actions a test requires, or `None` when it constrains the action not at all.

    Only a plain `self.action == "x"` or `self.action in (...)` counts. Anything else
    reads as unconstrained, so an unrecognised guard widens the search rather than
    narrowing it.
    """
    match test:
        case ast.BoolOp(op=ast.And(), values=values):
            # Every operand must hold, so any one of them can supply the constraint.
            required = {action for value in values for action in (_action_literals(value) or set())}
            return required or None
        case ast.Compare(
            left=ast.Attribute(value=ast.Name(id="self"), attr="action"),
            ops=[ast.Eq()],
            comparators=[ast.Constant(value=str(action))],
        ):
            return {action}
        case ast.Compare(
            left=ast.Attribute(value=ast.Name(id="self"), attr="action"),
            ops=[ast.In()],
            comparators=[ast.Tuple(elts=elements) | ast.List(elts=elements) | ast.Set(elts=elements)],
        ):
            actions = {element.value for element in elements if isinstance(element, ast.Constant)}
            return {action for action in actions if isinstance(action, str)} or None
        case _:
            return None


def _required_actions(test: ast.expr, view_class: type) -> set[str] | None:
    """The actions a branch test requires, following a `self.is_x()` guard one level.

    `InsightViewSet` gates its basic serializer on `self._is_basic_request()`, and that
    helper is where `self.action in ("list", "retrieve")` lives, so a guard that reads
    only the branch test would miss the constraint entirely.
    """
    direct = _action_literals(test)
    if direct is not None:
        return direct
    match test:
        case ast.Call(func=ast.Attribute(value=ast.Name(id="self"), attr=str(name)), args=[], keywords=[]):
            for klass in view_class.__mro__:
                helper = vars(klass).get(name)
                if helper is None:
                    continue
                try:
                    tree = ast.parse(textwrap.dedent(inspect.getsource(helper)))
                except Exception:
                    return None
                returned = [
                    node.value for node in ast.walk(tree) if isinstance(node, ast.Return) and node.value is not None
                ]
                return _action_literals(returned[0]) if len(returned) == 1 else None
    return None


def _returns_by_action(body: list[ast.stmt], view_class: type) -> list[tuple[ast.expr, set[str] | None]]:
    """Each returned expression, paired with the actions that have to hold to reach it.

    Only the taken branch of an action guard narrows. An `else` inherits the enclosing
    constraint instead of the complement, which keeps the result a superset.
    """
    found: list[tuple[ast.expr, set[str] | None]] = []

    def walk(statements: list[ast.stmt], required: set[str] | None) -> None:
        for statement in statements:
            if isinstance(statement, ast.Return):
                if statement.value is not None:
                    found.append((statement.value, required))
                continue
            if isinstance(statement, ast.If):
                actions = _required_actions(statement.test, view_class)
                narrowed = required & actions if required and actions else actions or required
                walk(statement.body, narrowed)
                walk(statement.orelse, required)
                continue
            for field in ("body", "orelse", "finalbody"):
                nested = getattr(statement, field, None)
                if isinstance(nested, list):
                    walk(nested, required)

    walk(body, None)
    return found


def _is_super_delegation(expression: ast.expr) -> bool:
    """`return super().get_serializer_class()`, which the MRO walk already covers."""
    match expression:
        case ast.Call(func=ast.Attribute(value=ast.Call(func=ast.Name(id="super")), attr="get_serializer_class")):
            return True
        case _:
            return False


def _serializer_choices(view_class: type, action: str) -> tuple[set[type], list[str]]:
    """Every serializer a view could hand to this action, and what would not resolve.

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
        module = sys.modules.get(function.__module__)
        module_scope = vars(module) if module is not None else {}
        scope, locally_bound = _function_scope(tree, module_scope, view_class)
        found.update(locally_bound)
        for returned, required in _returns_by_action(tree.body, view_class):
            if required is not None and action not in required:
                continue
            resolved = _resolve(returned, scope, view_class)
            serializer_classes = [entry for entry in resolved if _is_serializer(entry)]
            if serializer_classes:
                found.update(serializer_classes)
            elif not resolved and not _is_super_delegation(returned):
                unresolved.append(f"{klass.__qualname__}.get_serializer_class -> {ast.unparse(returned)[:60]}")
    return found, unresolved


def _serializer_classes(declared: Any) -> set[type]:
    """The serializer classes behind a request-body declaration.

    A declaration is not always a class: `inline_serializer` returns an instance,
    `many=True` wraps the real serializer in a `ListSerializer`, and a media-type
    mapping holds one declaration per content type.
    """
    if isinstance(declared, dict):
        return {entry for value in declared.values() for entry in _serializer_classes(value)}
    if isinstance(declared, list | tuple):
        return {entry for value in declared for entry in _serializer_classes(value)}
    if isinstance(declared, serializers.ListSerializer):
        return _serializer_classes(declared.child)
    if isinstance(declared, serializers.BaseSerializer):
        return {type(declared)}
    if _is_serializer(declared):
        return {declared}
    return set()


def _request_body_serializers(view_class: type, handler_names: set[str]) -> set[type]:
    """Serializers an `@extend_schema(request=...)` decorator names on a write handler.

    drf-spectacular does not store the declaration as data. It builds a schema class
    that closes over `request` and keeps it in the handler's `kwargs`, so the value is
    read back out of that closure. `test_request_body_declarations_stay_readable` fails
    if a drf-spectacular upgrade moves it, rather than letting discovery narrow quietly.
    """
    found: set[type] = set()
    for name in handler_names:
        handler = getattr(view_class, name, None)
        handler_kwargs = getattr(handler, "kwargs", None)
        schema = handler_kwargs.get("schema") if isinstance(handler_kwargs, dict) else None
        for klass in getattr(schema, "__mro__", ()):
            getter = vars(klass).get("get_request_serializer")
            code = getattr(getter, "__code__", None)
            closure = getattr(getter, "__closure__", None) or ()
            for variable, cell in zip(getattr(code, "co_freevars", ()), closure):
                if variable == "request":
                    found |= _serializer_classes(cell.cell_contents)
    return found


def _write_exposed_serializers() -> tuple[set[type], dict[str, str]]:
    """Every serializer reachable from a write route, and everything that would not resolve."""
    found: set[type] = set()
    unresolved: dict[str, str] = {}
    for _path, method, callback in EndpointEnumerator().get_api_endpoints():
        view_class = getattr(callback, "cls", None)
        if method not in WRITE_METHODS or view_class is None:
            continue
        # A viewset routes the method to an action; a plain APIView handles it by name.
        actions = getattr(callback, "actions", None) or {}
        action = actions.get(method.lower()) or method.lower()
        choices, problems = _serializer_choices(view_class, action)
        found.update(choices)
        if problems:
            unresolved[_dotted_name(view_class)] = "; ".join(problems)
        found.update(_request_body_serializers(view_class, {method.lower(), action}))
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


def test_allowlist_entries_still_match_a_violation() -> None:
    # Without this, the lists drift: an entry survives a field being made read-only,
    # renamed, or dropped. It also catches the larger failure, a change that narrows
    # discovery, because the fields that fall out of the sweep leave their entries
    # unmatched instead of passing as allowed.
    violations, problems = collect_violations()
    stale = sorted((set(ALLOWED_WRITABLE) - set(violations)) | (set(UNCHECKED) - set(problems)))
    assert not stale, (
        "These ALLOWED_WRITABLE or UNCHECKED entries no longer match anything the guard found. "
        "Delete them if the field is now read-only or gone. If the field still exists, discovery "
        "stopped reaching it, which leaves its write route unchecked:\n" + "\n".join(stale)
    )


def test_discovery_reaches_dynamically_selected_serializers() -> None:
    discovered = {_dotted_name(serializer) for serializer in _write_exposed_serializers()[0]}
    missing = sorted(f"{name} ({why})" for name, why in HARD_TO_DISCOVER.items() if name not in discovered)
    assert not missing, (
        "Discovery no longer reaches these serializers, so a server-owned timestamp on one of them "
        "would pass the sweep above. Reading get_serializer_class statically is what finds them:\n" + "\n".join(missing)
    )


# Fixtures for the discovery tests below. They sit at module level because a view
# resolves a serializer name against the globals of the module that defines it, which
# is where every real serializer lives.
class ReadShapeSerializer(serializers.Serializer):
    pass


class WriteShapeSerializer(serializers.Serializer):
    pass


class BranchingViewSet(viewsets.GenericViewSet):
    def _wants_read_shape(self) -> bool:
        return self.action in ("list", "retrieve")

    def get_serializer_class(self) -> type[serializers.Serializer]:
        if self._wants_read_shape():
            return ReadShapeSerializer
        return WriteShapeSerializer


class OpaqueGuardViewSet(viewsets.GenericViewSet):
    def get_serializer_class(self) -> type[serializers.Serializer]:
        if self.request.headers.get("x-shape") == "read":
            return ReadShapeSerializer
        return WriteShapeSerializer


def _choose_serializer(action: str) -> type[serializers.Serializer]:
    return WriteShapeSerializer


class FactoryViewSet(viewsets.GenericViewSet):
    def get_serializer_class(self) -> type[serializers.Serializer]:
        return _choose_serializer(self.action)


class DelegatingViewSet(viewsets.GenericViewSet):
    def get_serializer_class(self) -> type[serializers.BaseSerializer]:
        return super().get_serializer_class()


def test_read_only_action_serializers_are_not_write_route_violations() -> None:
    # A serializer a view hands only to list or retrieve is not exposed to a write
    # request, so reporting it would send an owning team after a hole that is not there.
    # The guard follows `_wants_read_shape` to find the constraint, because a helper is
    # where InsightViewSet keeps it.
    assert _serializer_choices(BranchingViewSet, "create")[0] == {WriteShapeSerializer}
    assert _serializer_choices(BranchingViewSet, "list")[0] == {ReadShapeSerializer, WriteShapeSerializer}


def test_unrecognized_action_guard_keeps_every_serializer() -> None:
    # Narrowing on a guard the parser does not understand would drop a serializer a
    # write route can still reach, so an unreadable guard must constrain nothing.
    assert _serializer_choices(OpaqueGuardViewSet, "create")[0] == {ReadShapeSerializer, WriteShapeSerializer}


def test_unresolvable_serializer_factory_is_reported() -> None:
    # A factory call resolves to nothing, so the route would pass unchecked unless the
    # guard reports it. super().get_serializer_class() is the one call the MRO covers.
    assert _serializer_choices(FactoryViewSet, "create")[1] == [
        "FactoryViewSet.get_serializer_class -> _choose_serializer(self.action)"
    ]
    assert _serializer_choices(DelegatingViewSet, "create")[1] == []


def test_request_body_declarations_stay_readable() -> None:
    # drf-spectacular keeps `request=` in a closure rather than as data, so the reader
    # depends on its internals. An upgrade that moves it must fail here.
    class DeclaredBodySerializer(serializers.Serializer):
        pass

    @extend_schema_view(create=extend_schema(request=DeclaredBodySerializer))
    class DecoratedViewSet(viewsets.GenericViewSet):
        def create(self, request: Any) -> None: ...

    assert _request_body_serializers(DecoratedViewSet, {"create"}) == {DeclaredBodySerializer}


def test_request_body_declarations_normalize_to_classes() -> None:
    # inline_serializer returns an instance, and many=True wraps one in a ListSerializer.
    class BodySerializer(serializers.Serializer):
        pass

    assert _serializer_classes(BodySerializer(many=True)) == {BodySerializer}
    assert _serializer_classes({"application/json": BodySerializer()}) == {BodySerializer}
    inline = inline_serializer("InlineBody", fields={"name": serializers.CharField()})
    assert _serializer_classes(inline) == {type(inline)}


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
