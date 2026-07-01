from __future__ import annotations

import pytest
from unittest.mock import MagicMock

import grpc
from parameterized import parameterized

from posthog.exceptions import PersonHogUnavailable
from posthog.personhog_client.client import personhog_call


def _make_rpc_error(status_code: grpc.StatusCode) -> grpc.RpcError:
    error = grpc.RpcError()
    error.code = MagicMock(return_value=status_code)
    return error


class TestPersonhogCall:
    def test_returns_result_on_success(self):
        assert personhog_call("op", lambda: "ok") == "ok"

    @parameterized.expand(
        [
            ("unavailable", grpc.StatusCode.UNAVAILABLE),
            ("aborted", grpc.StatusCode.ABORTED),
            ("deadline_exceeded", grpc.StatusCode.DEADLINE_EXCEEDED),
            ("unknown", grpc.StatusCode.UNKNOWN),
        ]
    )
    def test_transient_grpc_error_becomes_retryable_503(self, _name: str, status_code: grpc.StatusCode):
        def fn():
            raise _make_rpc_error(status_code)

        with pytest.raises(PersonHogUnavailable) as exc_info:
            personhog_call("op", fn)

        assert exc_info.value.status_code == 503
        assert isinstance(exc_info.value.__cause__, grpc.RpcError)

    def test_non_transient_grpc_error_is_not_masked(self):
        original = _make_rpc_error(grpc.StatusCode.INVALID_ARGUMENT)

        def fn():
            raise original

        with pytest.raises(grpc.RpcError) as exc_info:
            personhog_call("op", fn)

        assert exc_info.value is original

    def test_reraise_as_takes_precedence_over_translation(self):
        class DummyDatabaseError(Exception):
            pass

        def fn():
            raise _make_rpc_error(grpc.StatusCode.UNAVAILABLE)

        with pytest.raises(DummyDatabaseError):
            personhog_call("op", fn, reraise_as=DummyDatabaseError)

    def test_non_grpc_exception_propagates_unchanged(self):
        def fn():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            personhog_call("op", fn)
