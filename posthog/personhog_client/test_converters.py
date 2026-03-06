import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from parameterized import parameterized

from posthog.personhog_client.converters import (
    GroupTypeMappingResult,
    proto_group_type_mapping_to_dict,
    proto_group_type_mapping_to_result,
)


def _make_proto_mapping(**kwargs) -> SimpleNamespace:
    """Create a mock proto GroupTypeMapping with the same attributes as the real proto."""
    defaults = {
        "id": 0,
        "team_id": 0,
        "project_id": 0,
        "group_type": "",
        "group_type_index": 0,
        "name_singular": "",
        "name_plural": "",
        "default_columns": b"",
        "detail_dashboard_id": 0,
        "created_at": 0,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestProtoGroupTypeMappingToDict:
    @parameterized.expand(
        [
            (
                "all_fields_populated",
                {
                    "id": 1,
                    "team_id": 10,
                    "project_id": 100,
                    "group_type": "organization",
                    "group_type_index": 0,
                    "name_singular": "Organization",
                    "name_plural": "Organizations",
                    "default_columns": json.dumps(["name", "industry"]).encode(),
                    "detail_dashboard_id": 42,
                    "created_at": 1700000000,
                },
                {
                    "group_type": "organization",
                    "group_type_index": 0,
                    "name_singular": "Organization",
                    "name_plural": "Organizations",
                    "detail_dashboard_id": 42,
                    "default_columns": ["name", "industry"],
                    "created_at": datetime.fromtimestamp(1700000000, tz=UTC),
                },
            ),
            (
                "proto_defaults_become_none",
                {"group_type_index": 1},
                {
                    "group_type": None,
                    "group_type_index": 1,
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard_id": None,
                    "default_columns": None,
                    "created_at": None,
                },
            ),
            (
                "empty_strings_become_none",
                {
                    "group_type": "",
                    "group_type_index": 2,
                    "name_singular": "",
                    "name_plural": "",
                    "default_columns": b"",
                    "detail_dashboard_id": 0,
                    "created_at": 0,
                },
                {
                    "group_type": None,
                    "group_type_index": 2,
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard_id": None,
                    "default_columns": None,
                    "created_at": None,
                },
            ),
            (
                "default_columns_json_bytes_parsed",
                {
                    "group_type": "company",
                    "group_type_index": 3,
                    "default_columns": json.dumps(["revenue", "size"]).encode(),
                },
                {
                    "group_type": "company",
                    "group_type_index": 3,
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard_id": None,
                    "default_columns": ["revenue", "size"],
                    "created_at": None,
                },
            ),
        ]
    )
    def test_conversion(self, _name: str, proto_kwargs: dict, expected: dict):
        proto = _make_proto_mapping(**proto_kwargs)
        assert proto_group_type_mapping_to_dict(proto) == expected  # type: ignore[arg-type]  # SimpleNamespace duck-types the proto


class TestProtoGroupTypeMappingToResult:
    @parameterized.expand(
        [
            ("basic", "organization", 0),
            ("different_index", "company", 3),
        ]
    )
    def test_conversion(self, _name: str, group_type: str, group_type_index: int):
        proto = _make_proto_mapping(group_type=group_type, group_type_index=group_type_index)
        result = proto_group_type_mapping_to_result(proto)  # type: ignore[arg-type]  # SimpleNamespace duck-types the proto
        assert result == GroupTypeMappingResult(group_type=group_type, group_type_index=group_type_index)

    def test_result_is_frozen(self):
        result = GroupTypeMappingResult(group_type="org", group_type_index=0)
        with pytest.raises(AttributeError):
            result.group_type = "changed"  # type: ignore
