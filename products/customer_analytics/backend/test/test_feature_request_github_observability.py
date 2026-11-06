from typing import Any

import time_machine
from unittest.mock import patch

from django.test import SimpleTestCase

import posthoganalytics
from celery.exceptions import Retry
from posthoganalytics.contexts import get_capture_exception_code_variables_context
from structlog.contextvars import bound_contextvars, clear_contextvars, get_contextvars, merge_contextvars
from structlog.testing import capture_logs

from products.customer_analytics.backend.tasks.tasks import (
    _capture_terminal_feature_request_github_failure,
    process_feature_request_github_issue,
)


class TestFeatureRequestGitHubTaskObservability(SimpleTestCase):
    def setUp(self) -> None:
        clear_contextvars()
        self.addCleanup(clear_contextvars)

    task_args = (
        "installation-1",
        "posthog/posthog",
        42,
        "Issue title",
        "closed",
        "completed",
        "2026-01-01T00:00:00+00:00",
    )

    def test_task_accepts_legacy_arguments_and_restores_parent_log_context(self) -> None:
        with (
            patch("products.customer_analytics.backend.tasks.tasks.process_github_issue_update") as process_update,
            bound_contextvars(github_delivery_id="parent-delivery", parent_context="present"),
        ):
            result = process_feature_request_github_issue.apply(args=self.task_args, task_id="legacy-task")
            context_after_task = get_contextvars()

        self.assertEqual(result.state, "SUCCESS")
        process_update.assert_called_once()
        self.assertEqual(context_after_task["github_delivery_id"], "parent-delivery")
        self.assertEqual(context_after_task["parent_context"], "present")

    def test_nonterminal_retry_does_not_capture_and_keeps_attempt_context_isolated(self) -> None:
        observed_request: dict[str, str | int | None] = {}

        def fail_retryably(**_kwargs: object) -> None:
            observed_request["task_id"] = process_feature_request_github_issue.request.id
            observed_request["retries"] = process_feature_request_github_issue.request.retries
            raise RuntimeError("retryable error")

        with (
            patch(
                "products.customer_analytics.backend.tasks.tasks.process_github_issue_update",
                side_effect=fail_retryably,
            ),
            patch("products.customer_analytics.backend.tasks.tasks.capture_exception") as capture_exception,
            bound_contextvars(github_delivery_id="parent-delivery"),
        ):
            with self.assertRaises(Retry) as raised:
                process_feature_request_github_issue.apply(
                    args=self.task_args,
                    kwargs={"github_delivery_id": "delivery-1", "github_received_at": "2026-01-01T00:00:00+00:00"},
                    task_id="retry-task",
                    retries=1,
                )
            context_after_task = get_contextvars()

        self.assertIsInstance(raised.exception.exc, RuntimeError)
        self.assertEqual(observed_request, {"task_id": "retry-task", "retries": 1})
        capture_exception.assert_not_called()
        self.assertEqual(context_after_task["github_delivery_id"], "parent-delivery")

    @time_machine.travel("2026-01-01T00:01:00+00:00", tick=False)
    def test_task_started_log_includes_delivery_correlation_and_age(self) -> None:
        with (
            patch("products.customer_analytics.backend.tasks.tasks.process_github_issue_update"),
            capture_logs(processors=[merge_contextvars]) as logs,
        ):
            result = process_feature_request_github_issue.apply(
                args=self.task_args,
                kwargs={"github_delivery_id": "started-delivery", "github_received_at": "2026-01-01T00:00:00+00:00"},
                task_id="started-task",
                retries=2,
            )

        self.assertEqual(result.state, "SUCCESS")

        self.assertIn(
            {
                "github_delivery_id": "started-delivery",
                "task_id": "started-task",
                "sync_attempt": 2,
                "delivery_age_seconds": 60.0,
            },
            [
                {key: log[key] for key in ("github_delivery_id", "task_id", "sync_attempt", "delivery_age_seconds")}
                for log in logs
                if log["event"] == "feature_request_github_task_started"
            ],
        )

    def test_terminal_retry_captures_a_sanitized_exception_once_without_masking_the_failure(self) -> None:
        original = RuntimeError("original failure")
        with (
            patch(
                "products.customer_analytics.backend.tasks.tasks.process_github_issue_update",
                side_effect=original,
            ),
            patch("products.customer_analytics.backend.tasks.tasks.capture_exception") as capture_exception,
        ):
            result = process_feature_request_github_issue.apply(
                args=self.task_args,
                kwargs={"github_delivery_id": "delivery-1", "github_received_at": "2026-01-01T00:00:00+00:00"},
                task_id="terminal-task",
                retries=3,
                throw=False,
            )

        self.assertEqual(result.state, "FAILURE")
        capture_exception.assert_called_once()
        captured_error, properties = capture_exception.call_args.args
        self.assertNotEqual(captured_error, original)
        self.assertEqual(type(captured_error).__name__, "FeatureRequestGitHubTaskFailed")
        self.assertEqual(
            properties,
            {
                "github_delivery_id": "delivery-1",
                "task_id": "terminal-task",
                "sync_attempt": 3,
                "installation_id": "installation-1",
                "github_received_at": "2026-01-01T00:00:00+00:00",
                "exception_type": "RuntimeError",
            },
        )

    def test_capture_failure_does_not_mask_the_original_terminal_failure(self) -> None:
        with (
            patch(
                "products.customer_analytics.backend.tasks.tasks.process_github_issue_update",
                side_effect=RuntimeError("original failure"),
            ),
            patch(
                "products.customer_analytics.backend.tasks.tasks.capture_exception",
                side_effect=RuntimeError("capture failure"),
            ),
        ):
            result = process_feature_request_github_issue.apply(args=self.task_args, retries=3, throw=False)

        self.assertEqual(result.state, "FAILURE")
        self.assertIsInstance(result.result, RuntimeError)
        self.assertEqual(str(result.result), "original failure")

    def test_terminal_capture_serializes_only_the_sanitized_exception_without_code_variables(self) -> None:
        captured_context: list[bool | None] = []
        enqueued: list[dict[str, Any]] = []
        client = posthoganalytics.Client("test-key", capture_exception_code_variables=True)
        self.addCleanup(client.shutdown)

        def fail_with_sensitive_context(**_kwargs: object) -> None:
            issue_title = " ".join(("private", "issue", "title"))
            repository = "/".join(("private", "repository"))
            issue_body = " ".join(("private", "issue", "body"))
            if not all((issue_title, repository, issue_body)):
                raise AssertionError
            try:
                raise ValueError(" ".join(("private", "cause")))
            except ValueError as error:
                raise RuntimeError(" ".join(("private", "original", "error"))) from error

        def capture_with_pinned_sdk(error: Exception, properties: dict[str, object]) -> None:
            captured_context.append(get_capture_exception_code_variables_context())
            client.capture_exception(error, properties=properties)

        def capture_serialized_exception(event: str, *, properties: dict[str, object], **_kwargs: object) -> str:
            enqueued.append({"event": event, "properties": properties})
            return "event-1"

        with (
            patch(
                "products.customer_analytics.backend.tasks.tasks.capture_exception",
                side_effect=capture_with_pinned_sdk,
            ),
            patch.object(client, "capture", side_effect=capture_serialized_exception),
            posthoganalytics.new_context(fresh=True, capture_exceptions=False),
            bound_contextvars(parent_context="present"),
        ):
            posthoganalytics.set_capture_exception_code_variables_context(True)
            try:
                fail_with_sensitive_context()
            except Exception as error:
                _capture_terminal_feature_request_github_failure(
                    error,
                    github_delivery_id="delivery-1",
                    task_id="terminal-task",
                    sync_attempt=3,
                    installation_id="installation-1",
                    github_received_at="2026-01-01T00:00:00+00:00",
                )
            self.assertEqual(get_contextvars()["parent_context"], "present")
            self.assertTrue(get_capture_exception_code_variables_context())

        self.assertEqual(captured_context, [False])
        self.assertEqual(len(enqueued), 1)
        serialized = repr(enqueued[0])
        for secret in (
            "private issue title",
            "private/repository",
            "private issue body",
            "private cause",
            "private original error",
        ):
            self.assertNotIn(secret, serialized)
        exception_list = enqueued[0]["properties"]["$exception_list"]
        self.assertFalse(any("vars" in frame for value in exception_list for frame in value["stacktrace"]["frames"]))
