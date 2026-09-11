from collections.abc import Collection
from dataclasses import replace
from typing import TYPE_CHECKING, Literal

from products.data_modeling.backend.facade import api as data_modeling_facade
from products.warehouse_sources.backend.facade import api as warehouse_facade

from ..facade.enums import SubjectType
from .subject_access import DenialContext, ReadableSubjects

if TYPE_CHECKING:
    from posthog.scopes import APIScopeObject, APIScopeObjectOrNotSupported

    from products.access_control.backend.facade.user_access_control import UserAccessControl

_SUBJECT_RESOURCES: dict[SubjectType, "APIScopeObject"] = {
    SubjectType.TABLE: "warehouse_table",
    SubjectType.VIEW: "warehouse_view",
    SubjectType.METRIC: "data_catalog",
}


def authorized_subject_types(
    access: "UserAccessControl",
    scopes: Collection[str] | None,
    *,
    write: bool = False,
    route_scope: "APIScopeObjectOrNotSupported | None" = None,
) -> frozenset[SubjectType]:
    level: Literal["editor", "viewer"] = "editor" if write else "viewer"
    return frozenset(
        kind
        for kind, resource in _SUBJECT_RESOURCES.items()
        if _scope_allows(
            scopes,
            resource if kind == SubjectType.METRIC or resource == route_scope else "warehouse_objects",
            write,
        )
        and _has_subject_access(access, kind, level)
    )


def _has_subject_access(access: "UserAccessControl", kind: SubjectType, level: Literal["editor", "viewer"]) -> bool:
    if access.check_access_level_for_resource(_SUBJECT_RESOURCES[kind], level):
        return True
    if access.team is None or kind == SubjectType.METRIC:
        return False
    if kind == SubjectType.TABLE:
        return bool(warehouse_facade.allowed_table_ids(access.team.id, access, required_level=level))
    return bool(data_modeling_facade.allowed_saved_query_ids(access.team.id, access, required_level=level))


def writable_subjects(
    context: DenialContext, access: "UserAccessControl", *, allowed: Collection[SubjectType]
) -> ReadableSubjects:
    """The subjects this caller may change, narrowed to the kinds ``allowed`` permits.

    Takes the restriction rather than a pre-restricted context: the two have to be applied in that
    order, and a caller that passed an unrestricted context would get a wider answer than its scopes
    allow.
    """
    context = restrict_subject_types(context, allowed)
    if access.team is None:
        return ReadableSubjects(table_ids=frozenset(), view_ids=frozenset())
    return ReadableSubjects(
        table_ids=context.readable.table_ids
        & warehouse_facade.allowed_table_ids(access.team.id, access, required_level="editor"),
        view_ids=context.readable.view_ids
        & data_modeling_facade.allowed_saved_query_ids(access.team.id, access, required_level="editor"),
        metric_ids=context.readable.metric_ids
        if access.check_access_level_for_resource("data_catalog", "editor")
        else frozenset(),
    )


def _scope_allows(scopes: Collection[str] | None, resource: str, write: bool) -> bool:
    if scopes is None or "*" in scopes or f"{resource}:write" in scopes:
        return True
    return not write and f"{resource}:read" in scopes


def restrict_subject_types(context: DenialContext, allowed: Collection[SubjectType]) -> DenialContext:
    denied = set(context.denied)
    if SubjectType.TABLE not in allowed:
        denied.update(context.metadata.table_names.values())
    if SubjectType.VIEW not in allowed:
        denied.update(context.metadata.view_names.values())
    return replace(
        context,
        denied=denied,
        readable=ReadableSubjects(
            table_ids=context.readable.table_ids if SubjectType.TABLE in allowed else frozenset(),
            view_ids=context.readable.view_ids if SubjectType.VIEW in allowed else frozenset(),
            metric_ids=context.readable.metric_ids if SubjectType.METRIC in allowed else frozenset(),
        ),
    )
