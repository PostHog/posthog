from types import SimpleNamespace

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from parameterized import parameterized

from products.approvals.backend.exemptions import (
    APPROVAL_APPLY_KEY,
    INTERNAL_WRITE_KEY,
    internal_write_context,
    is_exempt_write,
)

USER_REQUEST = SimpleNamespace(user="a-user")
SYSTEM_REQUEST = SimpleNamespace(is_system=True)
# A mock forwards any attribute as a truthy Mock, so a loose check would exempt every mocked write.
PROXY_REQUEST = SimpleNamespace(is_system=MagicMock())


class TestIsExemptWrite(SimpleTestCase):
    @parameterized.expand(
        [
            ("apply path replays an approved change", {APPROVAL_APPLY_KEY: True}, USER_REQUEST, True),
            ("product-internal write", {INTERNAL_WRITE_KEY: True}, USER_REQUEST, True),
            ("internal marker must be exactly True", {INTERNAL_WRITE_KEY: MagicMock()}, USER_REQUEST, False),
            ("system request", {}, SYSTEM_REQUEST, True),
            ("is_system must be exactly True", {}, PROXY_REQUEST, False),
            ("user-authored write is gated", {}, USER_REQUEST, False),
            ("viewset has no context but a system request", None, SYSTEM_REQUEST, True),
            ("viewset has no context and a user request", None, USER_REQUEST, False),
        ]
    )
    def test_exemption(self, _name, context, request, expected):
        assert is_exempt_write(SimpleNamespace(context=context), request) is expected

    def test_internal_write_context_does_not_alias_the_caller_context(self):
        caller_context = {"request": USER_REQUEST}

        merged = {**caller_context, **internal_write_context()}

        assert is_exempt_write(SimpleNamespace(context=merged), USER_REQUEST) is True
        # The same request can still carry a user-authored write, which must reach the gate.
        assert is_exempt_write(SimpleNamespace(context=caller_context), USER_REQUEST) is False
