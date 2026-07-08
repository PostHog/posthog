from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog

from products.dashboards.backend.models.dashboard import Dashboard
from products.exports.backend.models.subscription import Subscription
from products.product_analytics.backend.models.insight import Insight


@freeze_time("2022-01-01")
class TestSubscriptionActivityLog(BaseTest):
    def _create_subscription(self, **kwargs) -> Subscription:
        params: dict = {
            "team": self.team,
            "created_by": self.user,
            "title": "Weekly AI digest",
            "prompt": "Summarize last week's signups",
            "target_type": "email",
            "target_value": "test@posthog.com",
            "frequency": "weekly",
            "interval": 1,
            "start_date": datetime(2022, 1, 1, tzinfo=ZoneInfo("UTC")),
        }
        params.update(kwargs)
        return Subscription.objects.create(**params)

    def _subscription_logs(self):
        return ActivityLog.objects.filter(scope="Subscription").order_by("created_at")

    @parameterized.expand(
        [
            ("ai", lambda self: self._create_subscription(), "Weekly AI digest"),
            (
                "insight",
                lambda self: self._create_subscription(
                    prompt=None, title=None, insight=Insight.objects.create(team=self.team, name="My insight")
                ),
                "My insight",
            ),
            (
                "dashboard",
                lambda self: self._create_subscription(
                    prompt=None, title=None, dashboard=Dashboard.objects.create(team=self.team, name="My dashboard")
                ),
                "My dashboard",
            ),
        ]
    )
    def test_creating_subscription_logs_activity(
        self, _name: str, make_subscription: Callable[..., Subscription], expected_name: str
    ):
        subscription = make_subscription(self)

        logs = self._subscription_logs()
        assert logs.count() == 1
        assert logs[0].activity == "created"
        assert logs[0].item_id == str(subscription.id)
        assert logs[0].detail["name"] == expected_name

    def test_subscription_without_created_by_still_logs(self):
        self._create_subscription(created_by=None)

        assert self._subscription_logs().count() == 1

    def test_updating_ai_subscription_prompt_records_change(self):
        subscription = self._create_subscription()

        subscription.prompt = "Summarize last week's churn instead"
        subscription.save(update_fields=["prompt"])

        logs = self._subscription_logs()
        assert logs.count() == 2
        assert logs[1].activity == "updated"
        prompt_change = next(change for change in logs[1].detail["changes"] if change["field"] == "prompt")
        assert prompt_change["action"] == "changed"
        assert prompt_change["before"] == "Summarize last week's signups"
        assert prompt_change["after"] == "Summarize last week's churn instead"

    @parameterized.expand(
        [
            ("adding_a_prompt", None, "Now summarize signups", "created"),
            ("clearing_a_prompt", "Existing prompt", None, "deleted"),
        ]
    )
    def test_prompt_null_transitions_record_change(
        self, _name: str, before: str | None, after: str | None, expected_action: str
    ):
        subscription = self._create_subscription(prompt=before)

        subscription.prompt = after
        subscription.save(update_fields=["prompt"])

        prompt_change = next(
            change for change in self._subscription_logs()[1].detail["changes"] if change["field"] == "prompt"
        )
        assert prompt_change["action"] == expected_action
        assert prompt_change["before"] == before
        assert prompt_change["after"] == after

    def _unsaved_subscription(self, **kwargs) -> Subscription:
        return Subscription(
            frequency="weekly",
            interval=1,
            start_date=datetime(2022, 1, 1, tzinfo=ZoneInfo("UTC")),
            **kwargs,
        )

    @parameterized.expand(
        [
            (
                "ai_title_wins",
                lambda self: self._unsaved_subscription(title="My title", prompt="the prompt"),
                "My title",
            ),
            (
                "ai_prompt_snippet_when_no_title",
                lambda self: self._unsaved_subscription(prompt="x" * 80),
                "x" * 60,
            ),
            (
                "ai_whitespace_prompt_falls_back",
                lambda self: self._unsaved_subscription(prompt="   "),
                "AI report",
            ),
            (
                "insight_uses_insight_name",
                lambda self: self._unsaved_subscription(
                    insight=Insight.objects.create(team=self.team, name="Signups by week")
                ),
                "Signups by week",
            ),
            (
                "dashboard_uses_dashboard_name",
                lambda self: self._unsaved_subscription(
                    dashboard=Dashboard.objects.create(team=self.team, name="Growth")
                ),
                "Growth",
            ),
        ]
    )
    def test_display_name(self, _name: str, make_subscription: Callable[..., Subscription], expected: str):
        assert make_subscription(self).display_name == expected

    def test_soft_deleting_ai_subscription_records_change(self):
        subscription = self._create_subscription()

        subscription.deleted = True
        subscription.save(update_fields=["deleted"])

        logs = self._subscription_logs()
        assert logs.count() == 2
        assert logs[1].activity == "updated"
        deleted_change = next(change for change in logs[1].detail["changes"] if change["field"] == "deleted")
        assert deleted_change["before"] is False
        assert deleted_change["after"] is True

    def test_mixed_save_excludes_next_delivery_date_from_diff(self):
        subscription = self._create_subscription()

        subscription.prompt = "Updated prompt"
        subscription.next_delivery_date = datetime(2022, 3, 1, tzinfo=ZoneInfo("UTC"))
        subscription.save(update_fields=["prompt", "next_delivery_date"])

        changed_fields = {change["field"] for change in self._subscription_logs()[1].detail["changes"]}
        assert "prompt" in changed_fields
        assert "next_delivery_date" not in changed_fields

    def test_scheduler_save_with_update_fields_does_not_log(self):
        subscription = self._create_subscription()

        subscription.next_delivery_date = datetime(2022, 2, 1, tzinfo=ZoneInfo("UTC"))
        subscription.save(update_fields=["next_delivery_date"])

        # Only the original "created" entry — the schedule bump is excluded via signal_exclusions.
        assert self._subscription_logs().count() == 1

    def test_scheduler_save_without_update_fields_does_not_log(self):
        subscription = self._create_subscription()

        subscription.refresh_from_db()
        subscription.next_delivery_date = datetime(2022, 2, 1, tzinfo=ZoneInfo("UTC"))
        subscription.save()

        # signal_exclusions also covers the no-update_fields path: the mixin's changed-fields check
        # honours the exclusion list, so a schedule-only change never emits the signal.
        assert self._subscription_logs().count() == 1
