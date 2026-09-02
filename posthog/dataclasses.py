from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar, dataclass_transform, overload

_T = TypeVar("_T")


@overload
def frozen(cls: type[_T], /) -> type[_T]: ...


@overload
def frozen(
    *,
    frozen: bool = True,
    kw_only: bool = True,
    slots: bool = True,
    eq: bool = True,
    order: bool = False,
    repr: bool = True,
    unsafe_hash: bool = False,
    match_args: bool = True,
    weakref_slot: bool = False,
) -> Callable[[type[_T]], type[_T]]: ...


@dataclass_transform(frozen_default=True, kw_only_default=True)
def frozen(cls: Any = None, /, **kwargs: Any) -> Any:
    """House-default dataclass: frozen, keyword-only construction, slotted.

    Use instead of a bare @dataclass for internal value/result objects. Any dataclass
    flag can be overridden per class, e.g. @frozen(slots=False) when the class needs
    functools.cached_property, or @frozen(frozen=False) for a mutable builder.
    """
    kwargs.setdefault("frozen", True)
    kwargs.setdefault("kw_only", True)
    kwargs.setdefault("slots", True)
    wrap = dataclass(**kwargs)
    return wrap if cls is None else wrap(cls)
