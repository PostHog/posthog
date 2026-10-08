import uuid

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.github.metrics import GitHubWebhookAnalyticsEvent
from posthog.github.pull_request_events import PullRequestAttribution, capture_pr_event


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
                "products.signals.backend.facade.github.resolve_github_login_distinct_id", return_value="reviewer-id"
            ),
            patch("posthog.github.attribution.bounded_statement_timeout"),
            patch(
                "posthog.github.pull_request_events._resolve_github_login_distinct_id",
                return_value="reviewer-id",
            ),
            patch("posthog.github.pull_request_events.posthoganalytics.capture") as capture,
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
