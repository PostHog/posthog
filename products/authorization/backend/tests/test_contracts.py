from typing import Any
from uuid import UUID

from django.test import SimpleTestCase

from parameterized import parameterized

from products.authorization.backend.facade.contracts import ObjectIds, Resource, Subject
from products.authorization.backend.facade.enums import ResourceType

PROJECT = Resource(type=ResourceType.PROJECT, id="1")


class TestSubject(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_field", {}),
            ("two_ids", {"user_id": 1, "api_key_id": "key_1"}),
            ("id_and_members", {"role_id": UUID(int=1), "members_of": PROJECT}),
        ]
    )
    def test_rejects_zero_or_several_fields(self, _name: str, kwargs: dict[str, Any]) -> None:
        with self.assertRaises(ValueError):
            Subject(**kwargs)

    @parameterized.expand([("user_id", {"user_id": 1}), ("members_of", {"members_of": PROJECT})])
    def test_accepts_exactly_one_field(self, _name: str, kwargs: dict[str, Any]) -> None:
        Subject(**kwargs)


class TestObjectIds(SimpleTestCase):
    @parameterized.expand(
        [
            ("only", ObjectIds(ids=frozenset({"1"}), complete=True), True, False, False),
            ("except", ObjectIds(ids=frozenset({"1"}), complete=True, excluded=True), False, True, True),
            ("all", ObjectIds(ids=frozenset(), complete=True, excluded=True), True, True, True),
            ("none", ObjectIds(ids=frozenset(), complete=True), False, False, False),
            ("creator", ObjectIds(ids=frozenset(), complete=True, creator_exempt=True), False, False, True),
            ("capped_creator", ObjectIds(ids=frozenset(), complete=False, creator_exempt=True), False, False, False),
        ]
    )
    def test_membership_and_creator_exemption(
        self, _name: str, result: ObjectIds, first: bool, other: bool, own: bool
    ) -> None:
        assert result.allows("1") is first
        assert result.allows("2", created_by_user_id=None, subject_user_id=1) is other
        assert result.allows("2", created_by_user_id=1, subject_user_id=1) is own
