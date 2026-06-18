from importlib import import_module
from os import environ
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from common.hogql.dependencies import HogQLQueryProvider

BACKEND_HOOKS_MODULE_ENV = "HOGQL_BACKEND_HOOKS_MODULE"


class HogQLBackendHooks(Protocol):
    def resolve_symbol(self, module: str, name: str) -> Any: ...

    def create_default_query_modifiers(self) -> Any: ...

    def get_project_id_for_team(self, team_id: int) -> int: ...

    def get_query_provider(self) -> "HogQLQueryProvider": ...


_backend_hooks: HogQLBackendHooks | None = None
_loading_backend_hooks = False


def set_hogql_backend_hooks(hooks: HogQLBackendHooks) -> None:
    global _backend_hooks

    _backend_hooks = hooks


def get_hogql_backend_hooks() -> HogQLBackendHooks:
    global _loading_backend_hooks

    if _backend_hooks is not None:
        return _backend_hooks

    if _loading_backend_hooks:
        raise RuntimeError("HogQL backend hooks are being loaded recursively")

    module_name = environ.get(BACKEND_HOOKS_MODULE_ENV)
    if not module_name:
        raise RuntimeError("HogQL backend hooks are not configured")

    _loading_backend_hooks = True
    try:
        module = import_module(module_name)
        install = getattr(module, "install_hogql_backend_hooks", None)
        if install is not None:
            install()
    finally:
        _loading_backend_hooks = False

    hooks = _backend_hooks
    if hooks is None:
        raise RuntimeError(f"HogQL backend hooks module {module_name!r} did not register hooks")

    return hooks  # type: ignore[unreachable]
