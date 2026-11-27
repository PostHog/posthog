from __future__ import annotations

from collections.abc import Callable
from dataclasses import MISSING, dataclass, field
from typing import Any, TypeVar, dataclass_transform, overload

_T = TypeVar("_T")


@overload
def described(help_text: str, /) -> Any: ...


@overload
def described(help_text: str, /, *, default: _T) -> _T: ...


def described(help_text: str, /, *, default: Any = MISSING) -> Any:
    """A dataclass field that carries its own API documentation.

    rest_framework_dataclasses merges the `serializer_kwargs` metadata into the serializer field
    it builds, so a `DataclassSerializer` publishes the text as the field's OpenAPI description.
    """
    return field(default=default, metadata={"serializer_kwargs": {"help_text": help_text}})


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


# Without field_specifiers a type checker reads every `= field(...)` or `= described(...)` as a
# default, so a field without one would stop being a required constructor argument.
@dataclass_transform(frozen_default=True, kw_only_default=True, field_specifiers=(field, described))
def frozen(cls: Any = None, /, **kwargs: Any) -> Any:
    """House-default dataclass: frozen, keyword-only construction, slotted.

    Use instead of a bare @dataclass for internal value/result objects. Any dataclass
    flag can be overridden per class, e.g. @frozen(slots=False) when the class needs
    functools.cached_property, or @frozen(frozen=False) for a mutable builder.
    """
    return dataclass(cls, **{"frozen": True, "kw_only": True, "slots": True, **kwargs})
