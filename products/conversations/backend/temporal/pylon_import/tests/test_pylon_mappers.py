from parameterized import parameterized

from products.conversations.backend.models.constants import Priority, Status
from products.conversations.backend.temporal.pylon_import.mappers import (
    map_pylon_author_type,
    map_pylon_priority,
    map_pylon_state,
)

CUSTOM_STATUS_CATEGORIES = {"escalated": "on_hold", "shipped": "closed", "odd": "something_new"}


class TestPylonMappers:
    @parameterized.expand(
        [
            ("new", Status.NEW),
            ("waiting_on_you", Status.OPEN),
            ("waiting_on_customer", Status.PENDING),
            ("on_hold", Status.ON_HOLD),
            ("closed", Status.RESOLVED),
            # Custom statuses resolve through their category.
            ("escalated", Status.ON_HOLD),
            ("shipped", Status.RESOLVED),
            # A category or slug the import does not know stays visible as open.
            ("odd", Status.OPEN),
            ("never_listed", Status.OPEN),
            (None, Status.OPEN),
        ]
    )
    def test_map_pylon_state(self, raw: str | None, expected: str) -> None:
        assert map_pylon_state(raw, CUSTOM_STATUS_CATEGORIES) == expected

    @parameterized.expand(
        [
            ("urgent", Priority.HIGH),
            ("high", Priority.HIGH),
            ("medium", Priority.MEDIUM),
            ("low", Priority.LOW),
            ("unexpected", None),
            (None, None),
        ]
    )
    def test_map_pylon_priority(self, raw: str | None, expected: str | None) -> None:
        assert map_pylon_priority(raw) == expected

    @parameterized.expand(
        [
            (False, True, ("customer", False)),
            (False, False, ("support", False)),
            (True, False, ("support", True)),
            # An internal note stays private even if its author resolves to a contact.
            (True, True, ("support", True)),
        ]
    )
    def test_map_pylon_author_type(self, is_private: bool, is_contact: bool, expected: tuple) -> None:
        assert map_pylon_author_type(is_private=is_private, is_contact=is_contact) == expected
