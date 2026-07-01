from parameterized import parameterized

from products.conversations.backend.models.constants import Priority, Status
from products.conversations.backend.temporal.zendesk_import.mappers import (
    map_zendesk_author_type,
    map_zendesk_priority,
    map_zendesk_status,
)


class TestZendeskMappers:
    @parameterized.expand(
        [
            ("new", Status.NEW),
            ("open", Status.OPEN),
            ("pending", Status.PENDING),
            ("hold", Status.ON_HOLD),
            ("solved", Status.RESOLVED),
            ("closed", Status.RESOLVED),
            ("unknown", Status.OPEN),
            (None, Status.NEW),
        ]
    )
    def test_map_zendesk_status(self, raw: str | None, expected: str) -> None:
        assert map_zendesk_status(raw) == expected

    @parameterized.expand(
        [
            ("low", Priority.LOW),
            ("normal", Priority.MEDIUM),
            ("high", Priority.HIGH),
            ("urgent", Priority.HIGH),
            (None, None),
        ]
    )
    def test_map_zendesk_priority(self, raw: str | None, expected: str | None) -> None:
        assert map_zendesk_priority(raw) == expected

    @parameterized.expand(
        [
            ("end-user", True, "customer", False),
            ("agent", True, "support", False),
            ("admin", True, "support", False),
            ("agent", False, "support", True),
        ]
    )
    def test_map_zendesk_author_type(
        self, role: str | None, is_public: bool, author_type: str, is_private: bool
    ) -> None:
        assert map_zendesk_author_type(role=role, is_public=is_public) == (author_type, is_private)
