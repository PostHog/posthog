from __future__ import annotations

import datetime

from posthog.temporal.data_imports.sources.common.sql.incremental import (
    build_incremental_fields,
    initial_value_for_incremental_type,
)

from products.data_warehouse.backend.types import IncrementalFieldType


def test_build_incremental_fields_emits_dict_per_triple() -> None:
    triples: list[tuple[str, IncrementalFieldType, bool]] = [
        ("created_at", IncrementalFieldType.DateTime, False),
        ("id", IncrementalFieldType.Integer, False),
    ]
    result = build_incremental_fields(triples)
    assert result == [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
            "nullable": False,
        },
        {
            "label": "id",
            "type": IncrementalFieldType.Integer,
            "field": "id",
            "field_type": IncrementalFieldType.Integer,
            "nullable": False,
        },
    ]


def test_build_incremental_fields_preserves_nullable_flag() -> None:
    result = build_incremental_fields([("updated_at", IncrementalFieldType.Timestamp, True)])
    assert result[0]["nullable"] is True


def test_build_incremental_fields_empty_input() -> None:
    assert build_incremental_fields([]) == []


def test_initial_value_for_integer_is_zero() -> None:
    assert initial_value_for_incremental_type(IncrementalFieldType.Integer) == 0


def test_initial_value_for_datetime_is_epoch() -> None:
    value = initial_value_for_incremental_type(IncrementalFieldType.DateTime)
    assert isinstance(value, datetime.datetime)
    assert value.year == 1970
