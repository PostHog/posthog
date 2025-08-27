import pytest
from posthog.test.base import BaseTest

from django.db.utils import IntegrityError

from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityLog, Change, Detail, log_activity
from posthog.models.utils import UUIDT


class TestActivityLogModel(BaseTest):
    def test_can_save_a_model_changed_activity_log(self) -> None:
        change = Change(
            type="FeatureFlag",
            field="active",
            action="created",
            before=False,
            after=True,
        )
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=self.user,
            was_impersonated=False,
            item_id=6,
            scope="FeatureFlag",
            activity="updated",
            detail=(Detail(changes=[change])),
        )
        log: ActivityLog = ActivityLog.objects.latest("id")

        self.assertEqual(log.team_id, self.team.id)
        self.assertEqual(log.organization_id, self.organization.id)
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.item_id, "6")
        self.assertEqual(log.scope, "FeatureFlag")
        self.assertEqual(log.activity, "updated")
        self.assertEqual(log.detail["changes"], [change.__dict__])

    def test_can_save_a_log_that_has_no_model_changes(self) -> None:
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=self.user,
            was_impersonated=False,
            item_id=None,
            scope="dinglehopper",
            activity="added_to_clink_expander",
            detail=Detail(),
        )
        log: ActivityLog = ActivityLog.objects.latest("id")
        self.assertEqual(log.activity, "added_to_clink_expander")

    def test_does_not_save_impersonated_activity_without_user(self) -> None:
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=None,
            was_impersonated=True,
            item_id=None,
            scope="dinglehopper",
            activity="added_to_clink_expander",
            detail=Detail(),
        )
        with pytest.raises(ActivityLog.DoesNotExist):
            ActivityLog.objects.filter(scope="dinglehopper").latest("id")

    def test_does_not_save_if_there_is_neither_a_team_id_nor_an_organisation_id(self) -> None:
        # even when there are logs with team id or org id saved
        ActivityLog.objects.create(team_id=3)
        ActivityLog.objects.create(organization_id=UUIDT())
        # we cannot save a new log if it has neither team nor org id
        with self.assertRaises(IntegrityError) as error:
            ActivityLog.objects.create()

        self.assertIn(
            'new row for relation "posthog_activitylog" violates check constraint "must_have_team_or_organization_id',
            error.exception.args[0],
        )

    def test_does_not_throw_if_cannot_log_activity(self) -> None:
        with self.assertLogs(level="WARN") as log:
            with self.settings(TEST=False):  # Enable production-level silencing
                try:
                    log_activity(
                        organization_id=UUIDT(),
                        team_id=1,
                        # will cause logging to raise exception because user is unsaved
                        # avoids needing to mock anything to force the exception
                        user=User(first_name="testy", email="test@example.com"),
                        was_impersonated=False,
                        item_id="12345",
                        scope="testing throwing exceptions on create",
                        activity="does not explode",
                        detail=Detail(),
                    )
                except Exception as e:
                    raise pytest.fail(f"Should not have raised exception: {e}")

            logged_warning = log.records[0].__dict__
            self.assertEqual(logged_warning["levelname"], "WARNING")
            self.assertEqual(
                logged_warning["msg"]["event"],
                "activity_log.failed_to_write_to_activity_log",
            )
            self.assertEqual(logged_warning["msg"]["scope"], "testing throwing exceptions on create")
            self.assertEqual(logged_warning["msg"]["team"], 1)
            self.assertEqual(logged_warning["msg"]["activity"], "does not explode")
            self.assertIsInstance(logged_warning["msg"]["exception"], ValueError)
