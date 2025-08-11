from collections.abc import Callable
from typing import Any, Literal, Optional, TypeVar, overload, cast
from pydantic import BaseModel


class LazyJoinFunctionBase(BaseModel):
    type: Literal["join_function"]
    name: str
    args: dict[str, Any]


class LazyJoinClosureSerialConfig(BaseModel):
    type: Literal["closure"]
    name: str
    args: dict[str, Any]


_REGISTERED_JOIN_FUNCTIONS: dict[str, Callable] = {}


_ALLOWED_RUNTIME_CLOSURE_NAMES: set[str] = {}

_F = TypeVar("_F", bound=Callable)


@overload
def register_join_function(_func: _F) -> _F: ...


@overload
def register_join_function(*, name: Optional[str] = ...) -> Callable[[_F], _F]: ...


def register_join_function(_func: Optional[_F] = None, *, name: Optional[str] = None):
    """
    Decorator to register a join function in the allowlist.

    Usage:
    - @register_join_function
    - @register_join_function()
    - @register_join_function(name="custom_name")
    """

    def _decorator(func: _F) -> _F:
        key = name or cast(str, getattr(func, "__name__", ""))
        # Register name -> callable mapping
        _REGISTERED_JOIN_FUNCTIONS[key] = func
        return func

    if _func is not None:
        return _decorator(_func)
    return _decorator


def is_join_function_allowed(func: Callable) -> bool:
    name = getattr(func, "__name__", "")
    if name in _REGISTERED_JOIN_FUNCTIONS:
        return True
    if name in _ALLOWED_RUNTIME_CLOSURE_NAMES:
        return True
    return False
