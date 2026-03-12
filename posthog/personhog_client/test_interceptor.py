from __future__ import annotations

from posthog.test.base import BaseTest

import grpc
from parameterized import parameterized

from posthog.personhog_client.interceptor import ClientNameInterceptor, _MutableClientCallDetails, _with_metadata


def _make_call_details(
    method: str = "/test/Method",
    metadata: list[tuple[str, str]] | None = None,
) -> grpc.ClientCallDetails:
    return _MutableClientCallDetails(
        method=method,
        timeout=5.0,
        metadata=metadata,
        credentials=None,
        wait_for_ready=None,
        compression=None,
    )


class TestWithMetadata(BaseTest):
    @parameterized.expand(
        [
            ("no_existing_metadata", None, [("x-key", "val")], [("x-key", "val")]),
            ("empty_existing_metadata", [], [("x-key", "val")], [("x-key", "val")]),
            (
                "preserves_existing_metadata",
                [("existing", "header")],
                [("x-key", "val")],
                [("existing", "header"), ("x-key", "val")],
            ),
            (
                "multiple_extra_entries",
                None,
                [("a", "1"), ("b", "2")],
                [("a", "1"), ("b", "2")],
            ),
        ]
    )
    def test_with_metadata(
        self,
        _name: str,
        existing_metadata: list[tuple[str, str]] | None,
        extra: list[tuple[str, str]],
        expected: list[tuple[str, str]],
    ) -> None:
        details = _make_call_details(metadata=existing_metadata)
        result = _with_metadata(details, extra)

        self.assertEqual(list(result.metadata), expected)
        self.assertEqual(result.method, details.method)
        self.assertEqual(result.timeout, details.timeout)


class TestClientNameInterceptor(BaseTest):
    @parameterized.expand(
        [
            ("default_name", "posthog-django"),
            ("web_deploy", "posthog-django-web"),
            ("worker_deploy", "posthog-django-worker"),
        ]
    )
    def test_injects_client_name(self, _name: str, client_name: str) -> None:
        interceptor = ClientNameInterceptor(client_name)
        original_details = _make_call_details()
        captured_details: list[grpc.ClientCallDetails] = []

        def mock_continuation(details: grpc.ClientCallDetails, request: object) -> str:
            captured_details.append(details)
            return "ok"

        result = interceptor.intercept_unary_unary(mock_continuation, original_details, request=b"")

        self.assertEqual(result, "ok")
        self.assertEqual(len(captured_details), 1)
        metadata = dict(captured_details[0].metadata)
        self.assertEqual(metadata["x-client-name"], client_name)
