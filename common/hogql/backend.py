from typing import Any

from common.hogql.dependencies import HogQLQueryProvider
from common.hogql.hooks import get_hogql_backend_hooks, get_optional_hogql_backend_hooks
from common.hogql.models import StandaloneHogQLQueryModifiers


def resolve_backend_symbol(module: str, name: str) -> Any:
    return get_hogql_backend_hooks().resolve_symbol(module, name)


def create_default_query_modifiers() -> Any:
    hooks = get_optional_hogql_backend_hooks()
    return hooks.create_default_query_modifiers() if hooks is not None else StandaloneHogQLQueryModifiers()


def get_project_id_for_team(team_id: int) -> int:
    return get_hogql_backend_hooks().get_project_id_for_team(team_id)


def get_query_provider() -> HogQLQueryProvider:
    return get_hogql_backend_hooks().get_query_provider()
