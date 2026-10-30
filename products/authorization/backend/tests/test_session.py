from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.authorization.backend.logic.session import Session


class TestSessionCaching(SimpleTestCase):
    @parameterized.expand([("transaction_still_open", True, False), ("transaction_ended", False, True)])
    def test_caching_after_an_uncommitted_write(self, _name: str, in_transaction: bool, expected: bool) -> None:
        session = Session(uncommitted=True)

        with patch("products.authorization.backend.logic.session.connection") as connection:
            connection.in_atomic_block = in_transaction
            assert session.can_cache() is expected
