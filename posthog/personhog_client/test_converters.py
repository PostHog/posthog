import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from parameterized import parameterized

from posthog.personhog_client.converters import (
    GroupTypeMappingResult,
    proto_group_to_model,
    proto_group_type_mapping_to_dict,
    proto_group_type_mapping_to_result,
    proto_person_to_model,
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
                    "created_at": 1700000000000,
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


def _make_proto_person(**kwargs) -> SimpleNamespace:
    defaults = {
        "id": 0,
        "uuid": "",
        "team_id": 0,
        "properties": b"",
        "properties_last_updated_at": b"",
        "properties_last_operation": b"",
        "created_at": 0,
        "version": 0,
        "is_identified": False,
        "is_user_id": False,
        "last_seen_at": 0,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestProtoPersonToModel:
    @parameterized.expand(
        [
            (
                "all_fields_populated",
                {
                    "id": 42,
                    "uuid": "550e8400-e29b-41d4-a716-446655440000",
                    "team_id": 10,
                    "properties": json.dumps({"email": "test@example.com", "name": "Test"}).encode(),
                    "created_at": 1700000000000,
                    "is_identified": True,
                    "last_seen_at": 1700000000000,
                },
                None,
            ),
            (
                "empty_properties",
                {"id": 1, "uuid": "550e8400-e29b-41d4-a716-446655440001", "team_id": 5},
                None,
            ),
            (
                "with_distinct_ids",
                {
                    "id": 7,
                    "uuid": "550e8400-e29b-41d4-a716-446655440002",
                    "team_id": 3,
                    "properties": json.dumps({"foo": "bar"}).encode(),
                    "created_at": 1700000000000,
                },
                ["did1", "did2"],
            ),
        ]
    )
    def test_conversion(self, _name: str, proto_kwargs: dict, distinct_ids: list[str] | None):
        proto = _make_proto_person(**proto_kwargs)
        person = proto_person_to_model(proto, distinct_ids=distinct_ids)  # type: ignore[arg-type]

        assert person.id == proto_kwargs.get("id", 0)
        assert str(person.uuid) == proto_kwargs.get("uuid", "")
        assert person.team_id == proto_kwargs.get("team_id", 0)
        assert person.is_identified == proto_kwargs.get("is_identified", False)

        raw_props = proto_kwargs.get("properties", b"")
        expected_props = json.loads(raw_props) if raw_props else {}
        assert person.properties == expected_props

        if proto_kwargs.get("created_at"):
            assert person.created_at == datetime.fromtimestamp(proto_kwargs["created_at"] / 1000, tz=UTC)
        else:
            # When proto has no created_at, we fall back to now() since the Django field is non-nullable
            assert isinstance(person.created_at, datetime)

        if proto_kwargs.get("last_seen_at"):
            assert person.last_seen_at == datetime.fromtimestamp(proto_kwargs["last_seen_at"] / 1000, tz=UTC)
        else:
            assert person.last_seen_at is None

        if distinct_ids is not None:
            assert person.distinct_ids == distinct_ids
        else:
            assert not hasattr(person, "_distinct_ids") or person._distinct_ids is None


def _make_proto_group(**kwargs) -> SimpleNamespace:
    defaults = {
        "id": 0,
        "team_id": 0,
        "group_type_index": 0,
        "group_key": "",
        "group_properties": b"",
        "created_at": 0,
        "properties_last_updated_at": b"",
        "properties_last_operation": b"",
        "version": 0,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestProtoGroupToModel:
    @parameterized.expand(
        [
            (
                "all_fields_populated",
                {
                    "id": 7,
                    "team_id": 10,
                    "group_type_index": 2,
                    "group_key": "org:123",
                    "group_properties": json.dumps({"name": "Acme", "industry": "tech"}).encode(),
                    "created_at": 1700000000000,
                    "properties_last_updated_at": json.dumps({"name": "2023-01-01T00:00:00Z"}).encode(),
                    "properties_last_operation": json.dumps({"name": "set"}).encode(),
                    "version": 5,
                },
            ),
            (
                "empty_proto_defaults",
                {
                    "id": 1,
                    "team_id": 3,
                    "group_type_index": 0,
                    "group_key": "anon",
                    "group_properties": b"",
                    "created_at": 0,
                    "properties_last_updated_at": b"",
                    "properties_last_operation": b"",
                    "version": 0,
                },
            ),
            (
                "json_properties_parsing",
                {
                    "id": 99,
                    "team_id": 5,
                    "group_type_index": 1,
                    "group_key": "company:456",
                    "group_properties": json.dumps({"revenue": 1000000, "employees": 50}).encode(),
                    "created_at": 1700000000000,
                    "properties_last_updated_at": b"",
                    "properties_last_operation": b"",
                    "version": 3,
                },
            ),
        ]
    )
    def test_conversion(self, _name: str, proto_kwargs: dict):
        proto = _make_proto_group(**proto_kwargs)
        group = proto_group_to_model(proto)  # type: ignore[arg-type]

        assert group.id == proto_kwargs["id"]
        assert group.team_id == proto_kwargs["team_id"]
        assert group.group_type_index == proto_kwargs["group_type_index"]
        assert group.group_key == proto_kwargs["group_key"]
        assert group.version == proto_kwargs["version"]

        raw_props = proto_kwargs.get("group_properties", b"")
        expected_props = json.loads(raw_props) if raw_props else {}
        assert group.group_properties == expected_props

        raw_last_updated = proto_kwargs.get("properties_last_updated_at", b"")
        expected_last_updated = json.loads(raw_last_updated) if raw_last_updated else {}
        assert group.properties_last_updated_at == expected_last_updated

        raw_last_op = proto_kwargs.get("properties_last_operation", b"")
        expected_last_op = json.loads(raw_last_op) if raw_last_op else {}
        assert group.properties_last_operation == expected_last_op

        if proto_kwargs.get("created_at"):
            assert group.created_at == datetime.fromtimestamp(proto_kwargs["created_at"] / 1000, tz=UTC)
        else:
            assert isinstance(group.created_at, datetime)

    def test_empty_group_properties_defaults_to_empty_dict(self):
        proto = _make_proto_group(id=1, team_id=1, group_key="k", group_properties=b"")
        group = proto_group_to_model(proto)  # type: ignore[arg-type]
        assert group.group_properties == {}

    def test_no_created_at_falls_back_to_now(self):
        proto = _make_proto_group(id=1, team_id=1, group_key="k", created_at=0)
        group = proto_group_to_model(proto)  # type: ignore[arg-type]
        assert isinstance(group.created_at, datetime)
        assert group.created_at.tzinfo is not None


class TestGroupTypeMappingDictKeysParity:
    def test_converter_dict_keys_match_orm_values_keys(self):
        from posthog.models.group_type_mapping import GROUP_TYPE_MAPPING_SERIALIZER_FIELDS

        proto = _make_proto_mapping(
            group_type="organization",
            group_type_index=0,
            name_singular="Org",
            name_plural="Orgs",
            detail_dashboard_id=42,
            default_columns=json.dumps(["name"]).encode(),
            created_at=1700000000000,
        )
        result = proto_group_type_mapping_to_dict(proto)  # type: ignore[arg-type]

        expected_keys = set()
        for field in GROUP_TYPE_MAPPING_SERIALIZER_FIELDS:
            if field == "detail_dashboard":
                expected_keys.add("detail_dashboard_id")
            else:
                expected_keys.add(field)

        assert set(result.keys()) == expected_keys

    def test_converter_malformed_default_columns_raises(self):
        proto = _make_proto_mapping(
            group_type="org",
            group_type_index=0,
            default_columns=b"not valid json",
        )
        with pytest.raises(json.JSONDecodeError):
            proto_group_type_mapping_to_dict(proto)  # type: ignore[arg-type]

    def test_group_converter_malformed_properties_raises(self):
        proto = _make_proto_group(
            id=1,
            team_id=1,
            group_key="k",
            group_properties=b"not valid json",
        )
        with pytest.raises(json.JSONDecodeError):
            proto_group_to_model(proto)  # type: ignore[arg-type]
