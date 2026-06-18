from typing import Any

from common.hogql.hooks import get_hogql_backend_hooks


def resolve_backend_symbol(module: str, name: str) -> Any:
    return get_hogql_backend_hooks().resolve_symbol(module, name)


def create_notice(
    *,
    start: int | None,
    end: int | None,
    message: str,
    fix: str | None,
) -> Any:
    return get_hogql_backend_hooks().create_notice(start=start, end=end, message=message, fix=fix)


def create_query_timing(*, kind: str, duration_seconds: float) -> Any:
    return get_hogql_backend_hooks().create_query_timing(kind=kind, duration_seconds=duration_seconds)


def create_default_query_modifiers() -> Any:
    return get_hogql_backend_hooks().create_default_query_modifiers()


def get_project_id_for_team(team_id: int) -> int:
    return get_hogql_backend_hooks().get_project_id_for_team(team_id)
