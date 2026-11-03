"""Access control checks that run on every API request a test makes.

- Referenced objects: an access-controlled object that a request names by id, and that the view loads by
  that id, needs an object-level access check before the request succeeds.
- Detail actions: a successful detail action on an access-controlled viewset needs an object-level check.
- Foreign keys: a serializer save must not point a foreign key at another project's object.
"""

import re
import json
import uuid
import functools
import threading
from collections import defaultdict
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from typing import Any

from django.apps import apps
from django.db import connections
from django.db.models import ForeignKey, Model, QuerySet
from django.db.models.lookups import Exact, In

from rest_framework import serializers
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import Team, User
from posthog.permissions import AccessControlPermission

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.access_control.backend.facade.user_access_control import (
    ACCESS_CONTROL_RESOURCES,
    UserAccessControl,
    model_to_resource,
)
from products.access_control.backend.presentation.access_control import (
    AccessControlViewSetMixin,
    UserAccessControlSerializerMixin,
)

# Findings that existed when these checks landed, as (check, "ViewSet.action" or "Model.field", model) -> reason.
# Fix the code and delete the row; a new finding gets a fix, not a row.
KNOWN_GAPS: dict[tuple[str, str, str], str] = {
    ("referenced_object", "DataQualityRunViewSet.create", "DataQualityCheck"): (
        "Authorized through access to each check's subject, which these checks cannot see."
    ),
    ("referenced_object", "SurveyViewSet.partial_update", "Action"): (
        "Actions already linked to the survey stay allowed. The view does not prefetch them, so these checks cannot "
        "tell them from new links without an extra query."
    ),
    ("referenced_object", "EventViewSet.list", "Action"): "Not fixed yet.",
    ("referenced_object", "InsightViewSet.create", "Action"): "Not fixed yet.",
    ("referenced_object", "ReviewQueueItemViewSet.create", "ReviewQueue"): "Not fixed yet.",
    ("referenced_object", "ReviewQueueItemViewSet.partial_update", "ReviewQueue"): "Not fixed yet.",
    ("referenced_object", "TraceReviewViewSet.partial_update", "ScoreDefinition"): "Not fixed yet.",
    ("referenced_object", "AutoresearchPipelineViewSet.create", "Action"): "Not fixed yet.",
    ("referenced_object", "AutoresearchPipelineViewSet.validate_definition", "Action"): "Not fixed yet.",
    ("referenced_object", "DataWarehouseExpressionViewSet.create", "ExternalDataSource"): (
        "The built-in managed warehouse connection is open to the whole project, so get_direct_connection_source "
        "skips the object check for it."
    ),
    ("detail_action", "HogFlowViewSet.cancel_invocations", ""): (
        "A deleted workflow has no row to check, so the view requires project-wide editor access instead."
    ),
}

_REFERENCE_KEY = re.compile(r"(^|_)(id|ids|pk|item|items)$|^(use|source|from)_")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_GATED = "_access_control_checks_gated"
_CONTROLLED = frozenset(ACCESS_CONTROL_RESOURCES)

_problems: list[str] = []
_foreign_keys: list[tuple[str, type[Model], Any, int]] = []
_state = threading.local()


class _Request:
    def __init__(self, candidates: set[str], detail_id: str | None) -> None:
        self.candidates = candidates
        self.detail_id = detail_id
        self.detail_models: set[type[Model]] = set()
        self.gated: set[tuple[str, str]] = set()
        self.loaded: dict[tuple[str, str], tuple[str, Any]] = {}
        self.object_checked = False
        self.displaying = 0
        self.stored: set[str] = set()
        self.wrote = False


def install() -> None:
    _wrap(APIView, "dispatch", _dispatch)
    _wrap(AccessControlPermission, "has_object_permission", _has_object_permission)
    _wrap(UserAccessControl, "get_user_access_level", _get_user_access_level)
    _wrap(UserAccessControl, "access_level_for_ref", _access_level_for_ref)
    _wrap(UserAccessControl, "bulk_object_access_levels", _bulk_object_access_levels)
    _wrap(UserAccessControl, "filter_queryset_by_access_level", _filter_queryset_by_access_level)
    _wrap(UserAccessControlSerializerMixin, "get_user_access_level", _display_access_level)
    _wrap(QuerySet, "_clone", _clone)
    _wrap(QuerySet, "_fetch_all", _fetch_all)
    _wrap(serializers.BaseSerializer, "save", _save)


def start_test() -> None:
    _problems.clear()
    _foreign_keys.clear()
    _state.request = None


def finish_test() -> list[str]:
    _check_foreign_keys()
    return list(_problems)


def _wrap(owner: type, name: str, wrapper: Callable[..., Any]) -> None:
    original = getattr(owner, name)

    @functools.wraps(original)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        return wrapper(original, *args, **kwargs)

    setattr(owner, name, wrapped)


def _active() -> _Request | None:
    return getattr(_state, "request", None)


def _report(check: str, subject: str, model: str, message: str) -> None:
    if (check, subject, model) not in KNOWN_GAPS:
        _problems.append(message)


_resources: dict[type[Model], str | None] = {}


@functools.cache
def _models_by_resource() -> dict[str, list[type[Model]]]:
    models: dict[str, list[type[Model]]] = defaultdict(list)
    for model in apps.get_models():
        resource = model_to_resource(model)
        if resource in _CONTROLLED:
            models[resource].append(model)
    return models


def _controlled_resource(model: type[Model]) -> str | None:
    # When a model is named after a shared resource, object rules attach to it alone, such as ReplayScanner
    # for replay_scanner; its observations take the scanner's access. Without one, as for llm_analytics,
    # each model takes its own rules.
    if model not in _resources:
        resource = model_to_resource(model)
        owner = resource.replace("_", "") if resource else ""
        if resource not in _CONTROLLED or (
            model._meta.model_name != owner
            and any(other._meta.model_name == owner for other in _models_by_resource()[resource])
        ):
            _resources[model] = None
        else:
            _resources[model] = resource
    return _resources[model]


def _checking() -> _Request | None:
    request = _active()
    return request if request is not None and not request.displaying else None


def _record_object(obj: Any) -> None:
    request = _checking()
    if request is None or isinstance(obj, Team):
        return
    request.object_checked = True
    resource = _controlled_resource(type(obj)) if isinstance(obj, Model) else None
    if resource is not None and obj.pk is not None:
        request.gated.add((resource, str(obj.pk)))


def _has_object_permission(
    original: Callable[..., bool], self: Any, request: Any, view: Any, obj: Any, *args: Any, **kwargs: Any
) -> bool:
    state = _active()
    if state is not None:
        state.object_checked = True
        if isinstance(obj, Model):
            _collect_stored(obj, state)
    return original(self, request, view, obj, *args, **kwargs)


def _collect_stored(obj: Model, state: _Request) -> None:
    # The object holds its references before the request changes it. Resending one on an edit adds
    # nothing new, so the referenced object check skips it.
    for field, value in obj.__dict__.items():
        if not field.startswith("_"):
            _collect(value, field.endswith("_id"), state.stored)
    for related in obj.__dict__.get("_prefetched_objects_cache", {}).values():
        state.stored.update(str(item.pk) for item in getattr(related, "_result_cache", related) or ())


def _get_user_access_level(
    original: Callable[..., Any], self: UserAccessControl, obj: Model, *args: Any, **kwargs: Any
) -> Any:
    _record_object(obj)
    return original(self, obj, *args, **kwargs)


def _access_level_for_ref(
    original: Callable[..., Any], self: UserAccessControl, ref: ObjectAccessRef, *args: Any, **kwargs: Any
) -> Any:
    request = _checking()
    if request is not None:
        request.object_checked = True
        request.gated.add((ref.resource, str(ref.id)))
    return original(self, ref, *args, **kwargs)


def _bulk_object_access_levels(
    original: Callable[..., Any],
    self: UserAccessControl,
    resource: str,
    objects: Iterable[tuple[str, Any]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    objects = list(objects)
    request = _checking()
    if request is not None:
        request.object_checked = True
        request.gated.update((resource, str(object_id)) for object_id, *_ in objects)
    return original(self, resource, objects, *args, **kwargs)


def _display_access_level(original: Callable[..., Any], self: Any, *args: Any, **kwargs: Any) -> Any:
    request = _active()
    if request is None:
        return original(self, *args, **kwargs)
    request.displaying += 1
    try:
        return original(self, *args, **kwargs)
    finally:
        request.displaying -= 1


def _filter_queryset_by_access_level(original: Callable[..., QuerySet], *args: Any, **kwargs: Any) -> QuerySet:
    queryset = original(*args, **kwargs)
    setattr(queryset, _GATED, True)
    request = _checking()
    if request is not None:
        request.object_checked = True
    return queryset


def _clone(original: Callable[..., QuerySet], self: QuerySet) -> QuerySet:
    clone = original(self)
    if getattr(self, _GATED, False):
        setattr(clone, _GATED, True)
    return clone


def _fetch_all(original: Callable[..., None], self: QuerySet) -> None:
    fetched = self._result_cache is None
    original(self)
    request = _active()
    if request is None or not fetched or not self._result_cache:
        return
    if request.detail_id is not None and self.model not in request.detail_models:
        for obj in self._result_cache:
            if isinstance(obj, Model) and str(obj.pk) == request.detail_id:
                request.detail_models.add(self.model)
                _collect_stored(obj, request)
    owner = getattr(self, "_hints", {}).get("instance")
    if (
        not request.wrote
        and isinstance(owner, Model)
        and type(owner) in request.detail_models
        and str(owner.pk) == request.detail_id
    ):
        # Rows under the object being edited, such as a review's scores, hold its references until the request writes.
        for row in self._result_cache:
            if isinstance(row, Model):
                _collect_stored(row, request)
            elif self.query.values_select:
                values = row.values() if isinstance(row, dict) else row if isinstance(row, tuple) else (row,)
                for name, value in zip(self.query.values_select, values):
                    if self.model._meta.get_field(name).is_relation:
                        _collect(value, True, request.stored)
    resource = _controlled_resource(self.model)
    if resource is None:
        return
    gated = getattr(self, _GATED, False)
    related = "instance" in getattr(self, "_hints", {})
    if gated and not isinstance(self._result_cache[0], Model):
        pk = self.model._meta.pk
        if pk is not None and self.query.values_select in ((pk.name,), (pk.attname,), ("pk",)):
            for row in self._result_cache:
                value = next(iter(row.values())) if isinstance(row, dict) else row[0] if isinstance(row, tuple) else row
                request.gated.add((resource, str(value)))
        return
    for obj in self._result_cache:
        if not isinstance(obj, Model) or obj.pk is None:
            return
        key = (resource, str(obj.pk))
        if gated:
            request.gated.add(key)
        elif key[1] in request.candidates and not related and _looked_up_by_pk(self, key[1]):
            request.loaded.setdefault(key, (type(obj).__name__, obj.__dict__.get("created_by_id")))


def _looked_up_by_pk(queryset: QuerySet, pk: str) -> bool:
    # Only a filter on this model's own primary key counts, so an id that matches by coincidence, or a
    # lookup through a joined table, does not.
    query = queryset.query
    base_table = query.base_table

    def matches(node: Any) -> bool:
        for child in getattr(node, "children", ()):
            if matches(child):
                return True
            if not isinstance(child, Exact | In):
                continue
            target = getattr(child.lhs, "target", None)
            if target is None or not target.primary_key or getattr(child.lhs, "alias", None) != base_table:
                continue
            values = child.rhs if isinstance(child, In) else [child.rhs]
            if isinstance(values, list | tuple | set) and any(str(value) == pk for value in values):
                return True
        return False

    return matches(query.where)


@functools.cache
def _has_team_id(model: type[Model]) -> bool:
    return any(field.attname == "team_id" for field in model._meta.concrete_fields)


def _save(original: Callable[..., Any], self: serializers.BaseSerializer, **kwargs: Any) -> Any:
    instance = original(self, **kwargs)
    team_id = getattr(instance, "team_id", None)
    if _active() is None or not isinstance(instance, Model) or team_id is None:
        return instance
    validated_data = getattr(self, "validated_data", None)
    touched = {*(validated_data if isinstance(validated_data, dict) else ()), *kwargs}
    for field in instance._meta.concrete_fields:
        related = field.related_model
        if not isinstance(field, ForeignKey) or not isinstance(related, type) or related is Team:
            continue
        if (field.name in touched or field.attname in touched) and _has_team_id(related):
            value = getattr(instance, field.attname)
            if value is not None:
                _foreign_keys.append((f"{type(instance).__name__}.{field.name}", related, value, team_id))
    return instance


def _check_foreign_keys() -> None:
    for subject, related, value, team_id in _foreign_keys:
        related_team_id = related._base_manager.filter(pk=value).values_list("team_id", flat=True).first()
        if related_team_id is None or related_team_id == team_id:
            continue
        projects = dict(Team.objects.filter(id__in={team_id, related_team_id}).values_list("id", "project_id"))
        if projects.get(team_id) != projects.get(related_team_id):
            _report(
                "foreign_key",
                subject,
                related.__name__,
                f"{subject} points at {related.__name__} {value} in team {related_team_id}, but the object is in "
                f"team {team_id}. Validate the id against the current project, for example with "
                "TeamScopedPrimaryKeyRelatedField.",
            )


def _request_candidates(request: Any) -> set[str]:
    candidates: set[str] = set()
    for key in request.GET:
        for value in request.GET.getlist(key):
            _collect(value, bool(_REFERENCE_KEY.search(key.lower())), candidates)
    if (request.META.get("CONTENT_TYPE") or "").startswith("application/json"):
        try:
            _collect(json.loads(request.body or b"null"), False, candidates)
        except Exception:
            pass
    return candidates


def _collect(value: Any, is_reference: bool, candidates: set[str], depth: int = 0) -> None:
    if depth > 8:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _collect(item, bool(_REFERENCE_KEY.search(str(key).lower())), candidates, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _collect(item, is_reference, candidates, depth + 1)
    elif isinstance(value, int) and not isinstance(value, bool):
        if is_reference:
            candidates.add(str(value))
    elif isinstance(value, str):
        if _UUID.match(value) or (is_reference and value.isdigit()):
            candidates.add(value)
    elif isinstance(value, uuid.UUID):
        candidates.add(str(value))
    elif isinstance(value, uuid.UUID):
        candidates.add(str(value))


def _note_write(state: _Request, execute: Callable[..., Any], sql: str, *args: Any) -> Any:
    if not state.wrote and sql.lstrip()[:6].upper() in ("INSERT", "UPDATE", "DELETE"):
        state.wrote = True
    return execute(sql, *args)


def _dispatch(original: Callable[..., Any], self: APIView, request: Any, *args: Any, **kwargs: Any) -> Any:
    if _active() is not None:
        return original(self, request, *args, **kwargs)
    lookup = str(getattr(self, "lookup_url_kwarg", None) or getattr(self, "lookup_field", None) or "pk")
    detail_id = kwargs.get(lookup)
    _state.request = state = _Request(_request_candidates(request), str(detail_id) if detail_id else None)
    try:
        with ExitStack() as stack:
            for connection in connections.all():
                stack.enter_context(connection.execute_wrapper(functools.partial(_note_write, state)))
            response = original(self, request, *args, **kwargs)
    finally:
        _state.request = None
    if not 200 <= response.status_code < 300:
        return response
    # Read what authentication already resolved: the public properties authenticate again when it has not run.
    drf_request = getattr(self, "request", None)
    user = getattr(drf_request, "_user", None)
    authenticator = type(getattr(drf_request, "_authenticator", None)).__name__
    if not isinstance(user, User) or "Sharing" in authenticator:
        return response
    action = getattr(self, "action", None) or request.method.lower()
    subject = f"{type(self).__name__}.{action}"
    for (resource, pk), (label, created_by_id) in sorted(state.loaded.items()):
        if (resource, pk) not in state.gated and pk not in state.stored and created_by_id != user.id:
            _report(
                "referenced_object",
                subject,
                label,
                f"{subject} loaded {label} {pk} by an id from the request without an object-level access check. "
                "Check it with user_access_control.check_access_level_for_object, or load it through "
                "filter_queryset_by_access_level.",
            )
    if _needs_object_check(self, request) and not state.object_checked:
        _report(
            "detail_action",
            subject,
            "",
            f"{subject} succeeded without an object-level access check. Load the object with self.get_object(), "
            "or call self.check_object_permissions(request, obj).",
        )
    return response


def _needs_object_check(view: APIView, request: Any) -> bool:
    if not isinstance(view, AccessControlViewSetMixin) or getattr(view, "detail", None) is not True:
        return False
    queryset = getattr(type(view), "queryset", None)
    if not isinstance(queryset, QuerySet) or _controlled_resource(queryset.model) is None:
        return False
    if request.method in ("HEAD", "OPTIONS"):
        return False
    if any(
        "dangerously_get_permissions" in vars(cls) for cls in type(view).__mro__ if cls is not TeamAndOrgViewSetMixin
    ):
        return False
    action_kwargs = getattr(getattr(view, getattr(view, "action", None) or "", None), "kwargs", None) or {}
    if "permission_classes" in action_kwargs and AccessControlPermission not in action_kwargs["permission_classes"]:
        return False
    try:
        return any(isinstance(permission, AccessControlPermission) for permission in view.get_permissions())
    except Exception:
        return False
