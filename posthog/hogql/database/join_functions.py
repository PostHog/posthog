from collections.abc import Callable
from typing import Any, Literal, Optional, TypeVar, overload, cast
from pydantic import BaseModel


class LazyJoinFunctionSerialConfig(BaseModel):
    type: Literal["join_function"] = "join_function"
    name: str


class LazyJoinClosureSerialConfig(BaseModel):
    type: Literal["closure"] = "closure"
    name: str
    args: tuple[Any, ...]


REGISTERED_JOIN_FUNCTIONS: dict[str, Callable] = {}


REGISTERED_JOIN_CLOSURES: dict[str, Callable] = {}

_F = TypeVar("_F", bound=Callable)


@overload
def register_join_function(_func: _F) -> _F: ...


@overload
def register_join_function(*, name: Optional[str] = ..., closure: bool = ...) -> Callable[[_F], _F]: ...


def register_join_function(_func: Optional[_F] = None, *, name: Optional[str] = None, closure: bool = False):
    """
    Decorator to register a join function in the allowlist.

    Usage:
    - @register_join_function
    - @register_join_function()
    - @register_join_function(name="custom_name")
    - @register_join_function(closure=True)  # for factory functions returning a join callable
    """

    def _decorator(func: _F) -> _F:
        key = name or cast(str, getattr(func, "__name__", ""))
        if closure:
            REGISTERED_JOIN_CLOSURES[key] = func
        else:
            REGISTERED_JOIN_FUNCTIONS[key] = func
        return func

    if _func is not None:
        return _decorator(_func)
    return _decorator


def is_join_function_allowed(func: Callable) -> bool:
    name = getattr(func, "__name__", "")
    if name in REGISTERED_JOIN_FUNCTIONS:
        return True
    if name in REGISTERED_JOIN_CLOSURES:
        return True
    return False
