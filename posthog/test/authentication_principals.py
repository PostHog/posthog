from types import NoneType, UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from rest_framework.authentication import BaseAuthentication


def _union_members(hint: Any) -> tuple[Any, ...]:
    return get_args(hint) if get_origin(hint) in (Union, UnionType) else (hint,)


def principal_types(authentication_class: type) -> set[Any]:
    """The types that `authenticate()` declares for the principal DRF sets as `request.user`."""
    assert issubclass(authentication_class, BaseAuthentication)
    returned = get_type_hints(authentication_class.authenticate).get("return")
    tuples = [member for member in _union_members(returned) if get_origin(member) is tuple]
    principals = {principal for member in tuples for principal in _union_members(get_args(member)[0])}
    return {NoneType if principal is None else principal for principal in principals}


def is_concrete(principals: set[Any]) -> bool:
    # `typing.Any` is a class too, so it needs its own check.
    return bool(principals) and all(isinstance(principal, type) and principal is not Any for principal in principals)
