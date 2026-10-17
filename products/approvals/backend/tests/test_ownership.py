from types import SimpleNamespace
from uuid import uuid4

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.approvals.backend.ownership import scope_by_owner_state


class TestScopeByOwnerState(SimpleTestCase):
    @parameterized.expand(
        [
            ("remembers_the_rollout", [True, None], [True, True]),
            ("follows_a_rollback", [True, False, None], [True, False, False]),
            ("unknown_before_any_answer", [None], [None]),
        ]
    )
    def test_an_unanswered_read_returns_the_last_answer(
        self, _name: str, reads: list[bool | None], expected: list[bool | None]
    ) -> None:
        organization = SimpleNamespace(id=uuid4())

        with patch("products.approvals.backend.ownership.posthoganalytics.feature_enabled", side_effect=reads):
            assert [scope_by_owner_state(organization) for _ in reads] == expected
