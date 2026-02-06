from datetime import datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db.models.signals import post_save
from django.utils import timezone

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog, activity_log_created

from ee.hogai.context.activity_log.context import MAX_VALUE_LENGTH, ActivityLogContext
from ee.hogai.context.activity_log.prompts import ACTIVITY_LOG_NO_RESULTS


class ActivityLogTestMixin:
    def setUp(self):
        super().setUp()
        post_save.disconnect(activity_log_created, sender=ActivityLog)

    def tearDown(self):
        post_save.connect(activity_log_created, sender=ActivityLog)
        super().tearDown()

    async def _create_log(
        self,
        *,
        scope: str = "FeatureFlag",
        activity: str = "updated",
        item_id: str = "1",
        detail: dict | None = None,
        user=None,
        is_system: bool = False,
        was_impersonated: bool = False,
        created_at: datetime | None = None,
    ) -> ActivityLog:
        return await ActivityLog.objects.acreate(
            team_id=self.team.id,
            user=user if user is not None and not is_system else (None if is_system else self.user),
            is_system=is_system,
            was_impersonated=was_impersonated,
            scope=scope,
            activity=activity,
            item_id=item_id,
            detail=detail or {},
            created_at=created_at or timezone.now(),
        )


@freeze_time("2025-06-15T12:00:00Z")
class TestActivityLogContext(ActivityLogTestMixin, BaseTest):
    def _create_context(self) -> ActivityLogContext:
        return ActivityLogContext(team=self.team, user=self.user)

    async def test_fetch_and_format_returns_no_results_message_when_empty(self):
        context = self._create_context()
        result = await context.fetch_and_format()
        assert result == ACTIVITY_LOG_NO_RESULTS

    async def test_fetch_and_format_returns_formatted_activity_logs(self):
        await self._create_log(
            scope="FeatureFlag",
            activity="created",
            item_id="42",
            detail={"name": "my-flag"},
        )
        context = self._create_context()
        result = await context.fetch_and_format()

        assert "Activity log" in result
        assert "1 entries" in result
        assert "FeatureFlag" in result
        assert "created" in result
        assert "my-flag" in result

    async def test_fetch_and_format_filters_by_scope(self):
        await self._create_log(scope="FeatureFlag", activity="created", item_id="1")
        await self._create_log(scope="Insight", activity="updated", item_id="2")

        context = self._create_context()
        result = await context.fetch_and_format(scope="FeatureFlag")

        assert "FeatureFlag" in result
        assert "Insight" not in result
        assert "for scope=FeatureFlag" in result

    async def test_fetch_and_format_filters_by_activity(self):
        await self._create_log(scope="FeatureFlag", activity="created", item_id="1")
        await self._create_log(scope="FeatureFlag", activity="deleted", item_id="2")

        context = self._create_context()
        result = await context.fetch_and_format(activity="created")

        assert "1 entries" in result
        assert "created" in result

    async def test_fetch_and_format_filters_by_item_id(self):
        await self._create_log(scope="FeatureFlag", item_id="10")
        await self._create_log(scope="FeatureFlag", item_id="20")

        context = self._create_context()
        result = await context.fetch_and_format(item_id="10")

        assert "1 entries" in result

    async def test_fetch_and_format_filters_by_user_email(self):
        await self._create_log(scope="Insight", activity="created", item_id="1")

        context = self._create_context()
        result = await context.fetch_and_format(user_email=self.user.email)

        assert "1 entries" in result
        assert f"by {self.user.email}" in result

    async def test_fetch_and_format_filters_by_user_email_no_match(self):
        await self._create_log(scope="Insight", activity="created", item_id="1")

        context = self._create_context()
        result = await context.fetch_and_format(user_email="nonexistent@example.com")

        assert result == ACTIVITY_LOG_NO_RESULTS

    async def test_fetch_and_format_respects_limit(self):
        for i in range(5):
            await self._create_log(item_id=str(i), created_at=timezone.now() - timedelta(minutes=i))

        context = self._create_context()
        result = await context.fetch_and_format(limit=2)

        assert "2 entries" in result

    async def test_fetch_and_format_clamps_limit_to_valid_range(self):
        for i in range(3):
            await self._create_log(item_id=str(i))

        context = self._create_context()

        result_low = await context.fetch_and_format(limit=0)
        assert "1 entries" in result_low

        result_high = await context.fetch_and_format(limit=100)
        assert "3 entries" in result_high

    async def test_fetch_and_format_orders_by_created_at_desc(self):
        await self._create_log(
            scope="Insight",
            activity="created",
            item_id="old",
            detail={"name": "OldInsight"},
            created_at=timezone.now() - timedelta(hours=2),
        )
        await self._create_log(
            scope="Insight",
            activity="updated",
            item_id="new",
            detail={"name": "NewInsight"},
            created_at=timezone.now(),
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        new_pos = result.index("NewInsight")
        old_pos = result.index("OldInsight")
        assert new_pos < old_pos

    async def test_system_action_shows_system_attribution(self):
        await self._create_log(
            scope="FeatureFlag",
            activity="updated",
            item_id="1",
            detail={"name": "sys-flag"},
            is_system=True,
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert "by System" in result

    async def test_impersonated_action_shows_impersonated_suffix(self):
        await self._create_log(
            scope="FeatureFlag",
            activity="updated",
            item_id="1",
            detail={"name": "imp-flag"},
            was_impersonated=True,
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert "(impersonated)" in result

    async def test_user_attribution_uses_first_name_when_available(self):
        self.user.first_name = "Alice"
        await self.user.asave()

        await self._create_log(scope="Insight", activity="created", item_id="1")

        context = self._create_context()
        result = await context.fetch_and_format()

        assert "by Alice" in result

    async def test_user_attribution_falls_back_to_email(self):
        self.user.first_name = ""
        await self.user.asave()

        await self._create_log(scope="Insight", activity="created", item_id="1")

        context = self._create_context()
        result = await context.fetch_and_format()

        assert f"by {self.user.email}" in result

    async def test_item_name_from_detail_name(self):
        await self._create_log(
            scope="FeatureFlag",
            activity="created",
            item_id="42",
            detail={"name": "my-feature-flag"},
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert "my-feature-flag" in result

    async def test_item_name_from_detail_short_id(self):
        await self._create_log(
            scope="Insight",
            activity="created",
            item_id="99",
            detail={"short_id": "abc123"},
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert "abc123" in result

    async def test_item_name_falls_back_to_item_id(self):
        await self._create_log(
            scope="Dashboard",
            activity="created",
            item_id="77",
            detail={},
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert "77" in result

    async def test_item_name_falls_back_to_unknown_when_no_detail_or_item_id(self):
        await ActivityLog.objects.acreate(
            team_id=self.team.id,
            user=self.user,
            is_system=False,
            was_impersonated=False,
            scope="Insight",
            activity="created",
            item_id=None,
            detail=None,
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert "(unknown)" in result

    @parameterized.expand(
        [
            (
                "created_change",
                [{"field": "enabled", "action": "created", "after": True}],
                "enabled: set to True",
            ),
            (
                "deleted_change",
                [{"field": "description", "action": "deleted", "before": "old desc"}],
                "description: removed (was old desc)",
            ),
            (
                "changed_value",
                [{"field": "name", "action": "changed", "before": "old", "after": "new"}],
                "name: old -> new",
            ),
        ]
    )
    async def test_format_changes(self, _name, changes, expected_text):
        await self._create_log(
            scope="FeatureFlag",
            activity="updated",
            item_id="1",
            detail={"name": "test", "changes": changes},
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert expected_text in result

    async def test_format_changes_with_none_values(self):
        await self._create_log(
            scope="FeatureFlag",
            activity="updated",
            item_id="1",
            detail={
                "name": "test",
                "changes": [{"field": "rollout", "action": "changed", "before": None, "after": 50}],
            },
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert "rollout: (none) -> 50" in result

    async def test_format_changes_empty_changes_list(self):
        await self._create_log(
            scope="FeatureFlag",
            activity="created",
            item_id="1",
            detail={"name": "no-changes", "changes": []},
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert "no-changes" in result
        assert "  - " not in result

    async def test_format_changes_non_dict_change_is_skipped(self):
        await self._create_log(
            scope="FeatureFlag",
            activity="updated",
            item_id="1",
            detail={
                "name": "test",
                "changes": [
                    "not-a-dict",
                    {"field": "name", "action": "changed", "before": "a", "after": "b"},
                ],
            },
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert "name: a -> b" in result


@freeze_time("2025-06-15T12:00:00Z")
class TestActivityLogContextTruncation(ActivityLogTestMixin, BaseTest):
    def _create_context(self) -> ActivityLogContext:
        return ActivityLogContext(team=self.team, user=self.user)

    async def test_truncate_large_string_value(self):
        long_value = "x" * (MAX_VALUE_LENGTH + 50)
        await self._create_log(
            scope="FeatureFlag",
            activity="updated",
            item_id="1",
            detail={
                "name": "test",
                "changes": [{"field": "description", "action": "changed", "before": "short", "after": long_value}],
            },
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert "..." in result
        assert long_value not in result

    async def test_truncate_large_dict_value(self):
        large_dict = {"key_" + str(i): "value_" + str(i) for i in range(100)}
        await self._create_log(
            scope="FeatureFlag",
            activity="updated",
            item_id="1",
            detail={
                "name": "test",
                "changes": [{"field": "filters", "action": "changed", "before": {}, "after": large_dict}],
            },
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert "..." in result

    async def test_truncate_large_list_value(self):
        large_list = list(range(200))
        await self._create_log(
            scope="FeatureFlag",
            activity="updated",
            item_id="1",
            detail={
                "name": "test",
                "changes": [{"field": "groups", "action": "changed", "before": [], "after": large_list}],
            },
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert "..." in result


@freeze_time("2025-06-15T12:00:00Z")
class TestActivityLogContextVisibility(ActivityLogTestMixin, BaseTest):
    def _create_context(self, user=None) -> ActivityLogContext:
        return ActivityLogContext(team=self.team, user=user or self.user)

    async def test_non_staff_user_cannot_see_restricted_scopes(self):
        self.user.is_staff = False
        await self.user.asave()

        await self._create_log(
            scope="User",
            activity="logged_in",
            item_id="1",
            detail={},
            was_impersonated=True,
        )
        await self._create_log(
            scope="User",
            activity="created",
            item_id="2",
            detail={"name": "user-created"},
        )
        await self._create_log(
            scope="FeatureFlag",
            activity="created",
            item_id="3",
            detail={"name": "visible-flag"},
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert "visible-flag" in result
        assert "logged_in" not in result
        assert "user-created" not in result

    async def test_staff_user_can_see_restricted_scopes(self):
        self.user.is_staff = True
        await self.user.asave()

        await self._create_log(
            scope="User",
            activity="logged_in",
            item_id="1",
            detail={"name": "staff-login"},
            was_impersonated=True,
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert "logged_in" in result

    @patch("ee.hogai.context.activity_log.context.get_activity_log_lookback_restriction")
    async def test_lookback_restriction_applied(self, mock_lookback):
        mock_lookback.return_value = timezone.now() - timedelta(days=7)

        await self._create_log(
            scope="FeatureFlag",
            activity="created",
            item_id="recent",
            detail={"name": "recent-flag"},
            created_at=timezone.now() - timedelta(days=1),
        )
        await self._create_log(
            scope="FeatureFlag",
            activity="created",
            item_id="old",
            detail={"name": "old-flag"},
            created_at=timezone.now() - timedelta(days=30),
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert "recent-flag" in result
        assert "old-flag" not in result

    @patch("ee.hogai.context.activity_log.context.get_activity_log_lookback_restriction")
    async def test_no_lookback_restriction_when_none(self, mock_lookback):
        mock_lookback.return_value = None

        await self._create_log(
            scope="FeatureFlag",
            activity="created",
            item_id="old",
            detail={"name": "old-flag"},
            created_at=timezone.now() - timedelta(days=365),
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert "old-flag" in result

    async def test_only_returns_entries_for_current_team(self):
        other_team_id = self.team.id + 9999

        await ActivityLog.objects.acreate(
            team_id=other_team_id,
            user=self.user,
            is_system=False,
            was_impersonated=False,
            scope="FeatureFlag",
            activity="created",
            item_id="1",
            detail={"name": "other-team-flag"},
        )
        await self._create_log(
            scope="FeatureFlag",
            activity="created",
            item_id="2",
            detail={"name": "my-team-flag"},
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert "my-team-flag" in result
        assert "other-team-flag" not in result

    async def test_includes_org_scoped_logs_when_enabled(self):
        self.team.receive_org_level_activity_logs = True
        await self.team.asave()

        await ActivityLog.objects.acreate(
            team_id=None,
            organization_id=self.team.organization_id,
            user=self.user,
            is_system=False,
            was_impersonated=False,
            scope="Organization",
            activity="updated",
            item_id=str(self.team.organization_id),
            detail={"name": "org-change"},
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert "org-change" in result

    async def test_excludes_org_scoped_logs_when_disabled(self):
        self.team.receive_org_level_activity_logs = False
        await self.team.asave()

        await ActivityLog.objects.acreate(
            team_id=None,
            organization_id=self.team.organization_id,
            user=self.user,
            is_system=False,
            was_impersonated=False,
            scope="Organization",
            activity="updated",
            item_id=str(self.team.organization_id),
            detail={"name": "org-change"},
        )

        context = self._create_context()
        result = await context.fetch_and_format()

        assert result == ACTIVITY_LOG_NO_RESULTS


@freeze_time("2025-06-15T12:00:00Z")
class TestActivityLogContextFormatting(ActivityLogTestMixin, BaseTest):
    async def test_timestamp_format(self):
        await self._create_log(
            scope="FeatureFlag",
            activity="created",
            item_id="1",
            detail={"name": "test"},
            created_at=timezone.now(),
        )

        context = ActivityLogContext(team=self.team, user=self.user)
        result = await context.fetch_and_format()

        assert "2025-06-15 12:00 UTC" in result

    async def test_entry_format_structure(self):
        await self._create_log(
            scope="Dashboard",
            activity="deleted",
            item_id="5",
            detail={"name": "My Dashboard"},
        )

        context = ActivityLogContext(team=self.team, user=self.user)
        result = await context.fetch_and_format()

        assert "- **2025-06-15 12:00 UTC** | Dashboard | deleted | My Dashboard" in result

    async def test_detail_with_non_dict_type_uses_item_id(self):
        await ActivityLog.objects.acreate(
            team_id=self.team.id,
            user=self.user,
            is_system=False,
            was_impersonated=False,
            scope="Insight",
            activity="created",
            item_id="42",
            detail="not-a-dict",
        )

        context = ActivityLogContext(team=self.team, user=self.user)
        result = await context.fetch_and_format()

        assert "42" in result
