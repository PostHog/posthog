from unittest.mock import Mock, patch

from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.api.github_webhooks.dispatch import dispatch_github_event


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
        self.assertEqual(response.status_code, 204 if fails else 202)
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
