import uuid

from unittest.mock import Mock, patch

from django.core.cache import cache
from django.db import InterfaceError, OperationalError
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.api.github_webhooks.contracts import PullRequestAttribution
from posthog.api.github_webhooks.dispatch import dispatch_github_event
from posthog.api.github_webhooks.metrics import GitHubWebhookAnalyticsEvent
from posthog.api.github_webhooks.pull_requests import capture_pr_event


class TestProductPullRequestAttribution(SimpleTestCase):
    @parameterized.expand(
        [
            ("created", "opened", False, "pr_created"),
            ("closed", "closed", False, "pr_closed"),
            ("merged", "closed", True, "pr_merged"),
            ("reviewed", "submitted", False, "pr_reviewed"),
        ]
    )
    def test_non_task_owner_uses_canonical_capture(
        self, _name: str, action: str, merged: bool, event: GitHubWebhookAnalyticsEvent
    ) -> None:
        pr_url = "https://github.com/example/app/pull/7"
        payload = {
            "action": action,
            "installation": {"id": 42},
            "repository": {"full_name": "example/app"},
            "pull_request": {
                "html_url": pr_url,
                "number": 7,
                "head": {"ref": "setup", "repo": {"full_name": "example/app"}},
                "merged": merged,
                "merged_by": {"login": "reviewer"},
                "body": "private PR content",
            },
            "review": {"id": 90, "state": "approved", "user": {"login": "reviewer", "type": "User"}},
        }
        attribution = PullRequestAttribution(
            source="wizard",
            team_id=12,
            distinct_id="creator",
            groups={"project": "12"},
            properties={"wizard_run_id": "example-run", "team_id": 999, "pr_source": "wrong", "pr_url": "wrong"},
        )

        with (
            patch(
                "posthog.api.github_webhooks.attribution.resolve_github_login_distinct_id", return_value="reviewer-id"
            ),
            patch("posthog.api.github_webhooks.attribution._bounded_attribution_lookup"),
            patch(
                "posthog.api.github_webhooks.pull_requests._resolve_github_login_distinct_id",
                return_value="reviewer-id",
            ),
            patch("posthog.api.github_webhooks.pull_requests.posthoganalytics.capture") as capture,
        ):
            for _ in range(2):
                capture_pr_event(payload, attribution, event)
            self.assertEqual(capture.call_count, 2)
            first, second = capture.call_args_list
            self.assertEqual(first.kwargs, second.kwargs)
            kwargs = first.kwargs
            self.assertEqual(kwargs["event"], event)
            self.assertEqual(
                kwargs["distinct_id"], "reviewer-id" if event in ("pr_merged", "pr_reviewed") else "creator"
            )
            self.assertEqual(kwargs["groups"], {"project": "12"})
            properties = kwargs["properties"]
            self.assertEqual(properties["wizard_run_id"], "example-run")
            self.assertEqual(properties["team_id"], 12)
            self.assertEqual(properties["pr_source"], "wizard")
            self.assertEqual(properties["pr_url"], pr_url)
            self.assertNotIn("task_id", properties)
            self.assertIsNone(properties["pr_body"])
            suffix = ":90" if event == "pr_reviewed" else ""
            self.assertEqual(
                kwargs["uuid"],
                str(uuid.uuid5(uuid.NAMESPACE_URL, f"{pr_url}:{event}{suffix}")),
            )


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class TestGitHubDispatch(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    @parameterized.expand([("success", False), ("failure", True)])
    def test_fanout_preserves_response_and_retries_only_failed_consumer(self, _name: str, fails: bool) -> None:
        request = RequestFactory().post("/webhooks/github/", data="{}", content_type="application/json")
        first = (
            Mock(side_effect=RuntimeError("consumer failed")) if fails else Mock(return_value=HttpResponse(status=202))
        )
        second = Mock(return_value=HttpResponse(status=204))
        with patch("posthog.api.github_webhooks.dispatch.capture_exception"):
            response = dispatch_github_event(
                request, "pull_request", {}, "delivery-example", [("tasks_pr_backstop", first), ("loops", second)]
            )
        self.assertEqual(response.status_code, 500 if fails else 202)
        self.assertEqual(second.call_count, 1)
        first.side_effect = None
        first.return_value = HttpResponse(status=202)
        response = dispatch_github_event(
            request, "pull_request", {}, "delivery-example", [("tasks_pr_backstop", first), ("loops", second)]
        )
        self.assertEqual(response.status_code, 202 if fails else 200)
        self.assertEqual(first.call_count, 2 if fails else 1)
        self.assertEqual(second.call_count, 1)
        self.assertTrue(cache.get("github_webhook_delivery:tasks_pr_backstop:delivery-example"))
        self.assertTrue(cache.get("github_webhook_delivery:loops:delivery-example"))

    @parameterized.expand(
        [
            ("operational_error_recovers", OperationalError("the connection is closed"), True, True, 2, 202),
            ("interface_error_recovers", InterfaceError("connection already closed"), True, True, 2, 202),
            ("connection_stays_down", OperationalError("the connection is closed"), True, False, 2, 500),
            ("connection_survives_the_error", OperationalError("canceling statement"), False, False, 1, 500),
        ]
    )
    def test_the_handler_runs_again_only_when_a_connection_died(
        self,
        _name: str,
        error: Exception,
        connection_died: bool,
        recovers: bool,
        expected_runs: int,
        expected_status: int,
    ) -> None:
        # A statement timeout raises OperationalError too, and close_if_unusable_or_obsolete keeps
        # that connection. Running the handler again would repeat its slow query for nothing.
        request = RequestFactory().post("/webhooks/github/", data="{}", content_type="application/json")
        handler = Mock(side_effect=[error, HttpResponse(status=202)] if recovers else error)
        db_connection = Mock(in_atomic_block=False, connection=None if connection_died else Mock())
        with (
            patch("posthog.api.github_webhooks.dispatch.connections") as db_connections,
            patch("posthog.api.github_webhooks.dispatch.capture_exception"),
        ):
            db_connections.all.return_value = [db_connection]
            response = dispatch_github_event(request, "push", {}, "delivery-blip", [("loops", handler)])

        self.assertEqual(handler.call_count, expected_runs)
        self.assertEqual(response.status_code, expected_status)
        self.assertEqual(cache.get("github_webhook_delivery:loops:delivery-blip"), True if recovers else None)
