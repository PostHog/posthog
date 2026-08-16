from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, TypeVar, dataclass_transform, overload

_T = TypeVar("_T")

REDACTED = "[redacted]"


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


def sensitive(**kwargs: Any) -> Any:
    """Field holding a secret: excluded from repr and masked by asdict_redacted().

    Accepts the same keyword arguments as dataclasses.field (default, default_factory, ...).
    """
    metadata = dict(kwargs.pop("metadata", None) or {})
    metadata["sensitive"] = True
    return field(repr=False, metadata=metadata, **kwargs)


def asdict_redacted(instance: Any) -> dict[str, Any]:
    """dataclasses.asdict with sensitive() fields masked.

    Use instead of asdict() when a dataclass is serialized for logs or error
    tracking; plain asdict() reintroduces the secrets that repr=False hides.
    None stays None so presence remains observable without leaking the value.
    """
    if not is_dataclass(instance) or isinstance(instance, type):
        raise TypeError("asdict_redacted() must be called on a dataclass instance")
    result = _redact(instance)
    assert isinstance(result, dict)
    return result


def _redact(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: (
                REDACTED
                if f.metadata.get("sensitive") and getattr(value, f.name) is not None
                else _redact(getattr(value, f.name))
            )
            for f in fields(value)
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    return value
