import dataclasses
from typing import Self

from posthog.dataclasses import frozen

from .roles import ROLE_MAP, normalize_role
from .values import Value, is_mapping


@frozen
class Scope:
    value: Value
    role: str

    @classmethod
    def for_node(cls, value: Value, inherited_role: str) -> Self:
        return cls(value=value, role=_resolve_role(value, inherited_role))

    def with_input(self, value: Value) -> Self:
        # An array element is a value to read fields from, not a new message, so it keeps the resolved role.
        return dataclasses.replace(self, value=value)


def _resolve_role(value: Value, inherited_role: str) -> str:
    if not is_mapping(value):
        return inherited_role
    role = value.get("role")
    if isinstance(role, str):
        return normalize_role(role, inherited_role)
    node_type = value.get("type")
    if isinstance(node_type, str) and node_type in ROLE_MAP:
        return normalize_role(node_type, inherited_role)
    return inherited_role
