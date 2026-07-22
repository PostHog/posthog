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
            # role, is_public, is_customer_side, expected_author_type, expected_is_private
            # Role is authoritative when resolved, regardless of customer-side membership.
            ("end_user", "end-user", True, True, "customer", False),
            ("end_user_non_customer_side", "end-user", True, False, "customer", False),
            ("agent", "agent", True, False, "support", False),
            ("admin", "admin", True, False, "support", False),
            # A second end-user (person2) in a thread resolves by role → customer, not staff.
            ("second_end_user", "end-user", True, False, "customer", False),
            ("agent_private_note", "agent", False, False, "support", True),
            # Role unresolved (hard-deleted): customer-side → customer, otherwise staff.
            ("deleted_customer_side", None, True, True, "customer", False),
            ("deleted_agent_not_customer_side", None, True, False, "support", False),
        ]
    )
    def test_map_zendesk_author_type(
        self,
        _name: str,
        role: str | None,
        is_public: bool,
        is_customer_side: bool,
        author_type: str,
        is_private: bool,
    ) -> None:
        assert map_zendesk_author_type(role=role, is_public=is_public, is_customer_side=is_customer_side) == (
            author_type,
            is_private,
        )
