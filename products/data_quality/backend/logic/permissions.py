from collections.abc import Collection
from dataclasses import replace
from typing import TYPE_CHECKING, Literal

from ..facade.enums import SubjectType
from .subject_access import DenialContext, ReadableSubjects

if TYPE_CHECKING:
    from posthog.scopes import APIScopeObject

    from products.access_control.backend.facade.user_access_control import UserAccessControl

_SUBJECT_RESOURCES: dict[SubjectType, "APIScopeObject"] = {
    SubjectType.TABLE: "warehouse_table",
    SubjectType.VIEW: "warehouse_view",
    SubjectType.METRIC: "data_catalog",
}


def authorized_subject_types(
    access: "UserAccessControl", scopes: Collection[str] | None, *, write: bool = False
) -> frozenset[SubjectType]:
    level: Literal["editor", "viewer"] = "editor" if write else "viewer"
    return frozenset(
        kind
        for kind, resource in _SUBJECT_RESOURCES.items()
        if access.check_access_level_for_resource(resource, level)
        and _scope_allows(scopes, "data_catalog" if kind == SubjectType.METRIC else "warehouse_objects", write)
    )


def _scope_allows(scopes: Collection[str] | None, resource: str, write: bool) -> bool:
    if scopes is None or "*" in scopes or f"{resource}:write" in scopes:
        return True
    return not write and f"{resource}:read" in scopes


def restrict_subject_types(context: DenialContext, allowed: Collection[SubjectType]) -> DenialContext:
    if context.metadata is None:
        raise ValueError("Subject metadata is required to restrict subject types")
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
