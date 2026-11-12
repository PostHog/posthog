from parameterized import parameterized

from products.conversations.backend.models.constants import Priority, Status
from products.conversations.backend.temporal.intercom_import.mappers import (
    map_intercom_author_type,
    map_intercom_priority,
    map_intercom_state,
)


class TestIntercomMappers:
    @parameterized.expand(
        [
            ("open", Status.OPEN),
            ("snoozed", Status.ON_HOLD),
            ("closed", Status.RESOLVED),
            ("unknown", Status.OPEN),
            (None, Status.OPEN),
        ]
    )
    def test_map_intercom_state(self, raw: str | None, expected: str) -> None:
        assert map_intercom_state(raw) == expected

    @parameterized.expand(
        [
            ("urgent", Priority.HIGH),
            ("high", Priority.HIGH),
            ("medium", Priority.MEDIUM),
            ("low", Priority.LOW),
            ("none", None),
            (None, None),
        ]
    )
    def test_map_intercom_priority(self, raw: str | None, expected: str | None) -> None:
        assert map_intercom_priority(raw) == expected

    @parameterized.expand(
        [
            ("user", "comment", ("customer", False)),
            ("lead", None, ("customer", False)),
            ("admin", "comment", ("support", False)),
            ("bot", "comment", ("support", False)),
            ("admin", "note", ("support", True)),
            # A note is internal even if the author resolves to a contact.
            ("user", "note", ("support", True)),
            # 2.18 reports part types it can't describe as `unknown`; never show those to the customer.
            ("admin", "unknown", ("support", True)),
        ]
    )
    def test_map_intercom_author_type(self, author_type: str, part_type: str | None, expected: tuple) -> None:
        assert map_intercom_author_type(author_type=author_type, part_type=part_type) == expected
