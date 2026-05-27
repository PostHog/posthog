from __future__ import annotations

from posthog.test.base import BaseTest

import grpc
from parameterized import parameterized

from posthog.personhog_client.interceptor import (
    CallerTagInterceptor,
    ClientNameInterceptor,
    ConsistencyHeaderInterceptor,
    _MutableClientCallDetails,
    _with_metadata,
    get_caller_tag,
    personhog_caller_tag,
    set_caller_tag,
)
from posthog.personhog_client.proto import (
    CONSISTENCY_LEVEL_EVENTUAL,
    CONSISTENCY_LEVEL_STRONG,
    GetPersonRequest,
    ReadOptions,
    UpdateGroupRequest,
)


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


class TestConsistencyHeaderInterceptor(BaseTest):
    @parameterized.expand(
        [
            (
                "strong_consistency",
                GetPersonRequest(
                    team_id=1,
                    person_id=42,
                    read_options=ReadOptions(consistency=CONSISTENCY_LEVEL_STRONG),
                ),
                "strong",
            ),
            (
                "eventual_consistency",
                GetPersonRequest(
                    team_id=1,
                    person_id=42,
                    read_options=ReadOptions(consistency=CONSISTENCY_LEVEL_EVENTUAL),
                ),
                "eventual",
            ),
            (
                "no_read_options_set",
                GetPersonRequest(team_id=1, person_id=42),
                "eventual",
            ),
            (
                "request_type_without_read_options",
                UpdateGroupRequest(team_id=1),
                "eventual",
            ),
        ]
    )
    def test_sets_consistency_header(self, _name: str, request: object, expected: str) -> None:
        interceptor = ConsistencyHeaderInterceptor()
        original_details = _make_call_details()
        captured_details: list[grpc.ClientCallDetails] = []

        def mock_continuation(details: grpc.ClientCallDetails, req: object) -> str:
            captured_details.append(details)
            return "ok"

        result = interceptor.intercept_unary_unary(mock_continuation, original_details, request=request)

        self.assertEqual(result, "ok")
        self.assertEqual(len(captured_details), 1)
        metadata = dict(captured_details[0].metadata)
        self.assertEqual(metadata["x-read-consistency"], expected)


class TestCallerTagInterceptor(BaseTest):
    def test_injects_default_unknown_tag(self) -> None:
        interceptor = CallerTagInterceptor()
        original_details = _make_call_details()
        captured_details: list[grpc.ClientCallDetails] = []

        def mock_continuation(details: grpc.ClientCallDetails, request: object) -> str:
            captured_details.append(details)
            return "ok"

        result = interceptor.intercept_unary_unary(mock_continuation, original_details, request=b"")

        self.assertEqual(result, "ok")
        metadata = dict(captured_details[0].metadata)
        self.assertEqual(metadata["x-caller-tag"], "unknown")

    def test_injects_tag_from_context(self) -> None:
        interceptor = CallerTagInterceptor()
        original_details = _make_call_details()
        captured_details: list[grpc.ClientCallDetails] = []

        def mock_continuation(details: grpc.ClientCallDetails, request: object) -> str:
            captured_details.append(details)
            return "ok"

        with personhog_caller_tag("api/feature-flags"):
            interceptor.intercept_unary_unary(mock_continuation, original_details, request=b"")

        metadata = dict(captured_details[0].metadata)
        self.assertEqual(metadata["x-caller-tag"], "api/feature-flags")


class TestCallerTagContextManager(BaseTest):
    def test_default_is_unknown(self) -> None:
        self.assertEqual(get_caller_tag(), "unknown")

    def test_context_manager_sets_and_resets(self) -> None:
        self.assertEqual(get_caller_tag(), "unknown")
        with personhog_caller_tag("celery/cohort-calculation"):
            self.assertEqual(get_caller_tag(), "celery/cohort-calculation")
        self.assertEqual(get_caller_tag(), "unknown")

    def test_nesting(self) -> None:
        with personhog_caller_tag("outer"):
            self.assertEqual(get_caller_tag(), "outer")
            with personhog_caller_tag("inner"):
                self.assertEqual(get_caller_tag(), "inner")
            self.assertEqual(get_caller_tag(), "outer")

    def test_set_caller_tag_function(self) -> None:
        token = set_caller_tag("manual-tag")
        self.assertEqual(get_caller_tag(), "manual-tag")
        from posthog.personhog_client.interceptor import _caller_tag

        _caller_tag.reset(token)
