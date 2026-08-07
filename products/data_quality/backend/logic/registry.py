"""Registry of the available check types.

The spec contract itself lives in ``spec.py``; this is only the lookup table, so adding a type is
one import and one entry.
"""

from ..facade.contracts import CheckTypeInfo
from ..facade.enums import CheckType
from .spec import CheckTypeSpec
from .types import accepted_values, custom_sql, freshness, not_null, relationships, row_count, unique

_SPECS: dict[CheckType, CheckTypeSpec] = {
    spec.type_name: spec
    for spec in (
        not_null.SPEC,
        unique.SPEC,
        accepted_values.SPEC,
        relationships.SPEC,
        row_count.SPEC,
        freshness.SPEC,
        custom_sql.SPEC,
    )
}


def get_spec(check_type: str) -> CheckTypeSpec:
    try:
        return _SPECS[CheckType(check_type)]
    except (KeyError, ValueError):
        raise UnknownCheckTypeError(check_type)


def all_specs() -> list[CheckTypeSpec]:
    return [_SPECS[check_type] for check_type in CheckType]


def list_check_types() -> list[CheckTypeInfo]:
    """The catalog, as plain values. What callers outside the compiler get instead of the specs."""
    return [
        CheckTypeInfo(
            check_type=spec.type_name.value,
            description=spec.description,
            requires_column=spec.requires_column,
            config_schema=spec.json_schema,
        )
        for spec in all_specs()
    ]


class UnknownCheckTypeError(ValueError):
    def __init__(self, check_type: str) -> None:
        supported = ", ".join(t.value for t in CheckType)
        super().__init__(f"Unknown check type '{check_type}'. Supported types: {supported}.")
