from importlib import import_module
from os import environ
from typing import Any, Protocol

BACKEND_HOOKS_MODULE_ENV = "HOGQL_BACKEND_HOOKS_MODULE"


class HogQLBackendHooks(Protocol):
    def resolve_symbol(self, module: str, name: str) -> Any: ...

    def create_notice(
        self,
        *,
        start: int | None,
        end: int | None,
        message: str,
        fix: str | None,
    ) -> Any: ...

    def create_query_timing(self, *, kind: str, duration_seconds: float) -> Any: ...

    def create_default_query_modifiers(self) -> Any: ...

    def get_project_id_for_team(self, team_id: int) -> int: ...


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

    if _backend_hooks is None:
        raise RuntimeError(f"HogQL backend hooks module {module_name!r} did not register hooks")

    return _backend_hooks
