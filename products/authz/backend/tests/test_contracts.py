from typing import Any
from uuid import UUID

from django.test import SimpleTestCase

from parameterized import parameterized

from products.authz.backend.facade.contracts import Resource, Subject
from products.authz.backend.facade.enums import ResourceType

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
