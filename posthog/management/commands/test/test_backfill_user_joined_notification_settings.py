import uuid
from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from posthog.management.commands.backfill_user_joined_notification_settings import ORG_MEMBER_JOIN_KEY
from posthog.models import Organization


class TestBackfillUserJoinedNotificationSettingsCommand(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.stdout = StringIO()

    def test_backfill_sets_flags_from_org_is_member_join_email_enabled(self) -> None:
        self.user.partial_notification_settings = {"plugin_disabled": False}
        self.user.save()

        org_disabled = Organization.objects.create(
            name="No join emails",
            is_member_join_email_enabled=False,
        )
        self.user.join(organization=org_disabled)

        self.organization.is_member_join_email_enabled = True
        self.organization.save()

        call_command("backfill_user_joined_notification_settings", stdout=self.stdout)

        self.user.refresh_from_db(fields=["partial_notification_settings"])
        pns = self.user.partial_notification_settings or {}
        self.assertEqual(pns.get("plugin_disabled"), False)
        join_map = pns.get(ORG_MEMBER_JOIN_KEY, {})
        self.assertEqual(join_map[str(self.organization.id)], False)
        self.assertEqual(join_map[str(org_disabled.id)], True)

    def test_dry_run_does_not_write(self) -> None:
        self.user.partial_notification_settings = None
        self.user.save()

        call_command("backfill_user_joined_notification_settings", "--dry-run", stdout=self.stdout)

        self.user.refresh_from_db(fields=["partial_notification_settings"])
        self.assertIsNone(self.user.partial_notification_settings)

    def test_backfill_preserves_other_top_level_notification_keys(self) -> None:
        before = {
            "plugin_disabled": False,
            "discussions_mentioned": False,
            "all_weekly_digest_disabled": True,
            "data_pipeline_error_threshold": 0.05,
            "project_weekly_digest_disabled": {str(self.team.id): True},
            "error_tracking_weekly_digest_project_enabled": {str(self.team.id): True},
        }
        self.user.partial_notification_settings = dict(before)
        self.user.save()

        call_command("backfill_user_joined_notification_settings", stdout=self.stdout)

        self.user.refresh_from_db(fields=["partial_notification_settings"])
        pns = self.user.partial_notification_settings or {}
        for key, value in before.items():
            self.assertEqual(pns.get(key), value, msg=f"expected {key!r} unchanged")
        join_map = pns.get(ORG_MEMBER_JOIN_KEY, {})
        self.assertEqual(join_map[str(self.organization.id)], False)

    def test_backfill_skips_users_who_already_have_join_notification_key(self) -> None:
        stale_org_id = str(uuid.uuid4())
        self.user.partial_notification_settings = {
            ORG_MEMBER_JOIN_KEY: {
                stale_org_id: True,
            },
        }
        self.user.save()

        call_command("backfill_user_joined_notification_settings", stdout=self.stdout)

        self.user.refresh_from_db(fields=["partial_notification_settings"])
        join_map = (self.user.partial_notification_settings or {}).get(ORG_MEMBER_JOIN_KEY, {})
        self.assertEqual(join_map.get(stale_org_id), True)
        self.assertNotIn(str(self.organization.id), join_map)
