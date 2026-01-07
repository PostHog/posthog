import pytest
from posthog.test.base import BaseTest

from django.db.utils import IntegrityError

from parameterized import parameterized

from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityLog, Change, Detail, log_activity
from posthog.models.activity_logging.utils import activity_visibility_manager
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

        assert log.team_id == self.team.id
        assert log.organization_id == self.organization.id
        assert log.user == self.user
        assert log.item_id == "6"
        assert log.scope == "FeatureFlag"
        assert log.activity == "updated"
        assert log.detail["changes"] == [change.__dict__]

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
        assert log.activity == "added_to_clink_expander"

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
        with pytest.raises(IntegrityError) as error:
            ActivityLog.objects.create()

        assert (
            'new row for relation "posthog_activitylog" violates check constraint "must_have_team_or_organization_id'
            in error.value.args[0]
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
            assert logged_warning["levelname"] == "WARNING"
            assert logged_warning["msg"]["event"] == "activity_log.failed_to_write_to_activity_log"
            assert logged_warning["msg"]["scope"] == "testing throwing exceptions on create"
            assert logged_warning["msg"]["team"] == 1
            assert logged_warning["msg"]["activity"] == "does not explode"
            assert isinstance(logged_warning["msg"]["exception"], ValueError)


class TestActivityLogVisibilityManager(BaseTest):
    @parameterized.expand(
        [
            # Restricted: impersonated login/logout should be hidden from external destinations
            ("impersonated_login", "User", "logged_in", True, True),
            ("impersonated_logout", "User", "logged_out", True, True),
            # Not restricted: normal (non-impersonated) login/logout are fine to show
            ("normal_login", "User", "logged_in", False, False),
            ("normal_logout", "User", "logged_out", False, False),
            # Not restricted: other User activities don't match the restriction
            ("user_updated", "User", "updated", True, False),
            ("user_changed_password", "User", "changed_password", False, False),
            # Not restricted: other scopes are unaffected
            ("feature_flag_created", "FeatureFlag", "created", False, False),
            ("feature_flag_updated", "FeatureFlag", "updated", True, False),
            ("insight_created", "Insight", "created", False, False),
            ("dashboard_deleted", "Dashboard", "deleted", False, False),
            ("experiment_launched", "Experiment", "launched", True, False),
        ]
    )
    def test_is_restricted_for_external_destinations(
        self, _name: str, scope: str, activity: str, was_impersonated: bool, expected_restricted: bool
    ) -> None:
        log = ActivityLog(
            team_id=self.team.id,
            scope=scope,
            activity=activity,
            was_impersonated=was_impersonated,
        )
        assert activity_visibility_manager.is_restricted(log, restrict_for_staff=True) == expected_restricted

    @parameterized.expand(
        [
            # Staff bypass: impersonated login/logout visible to staff via allow_staff=True
            ("impersonated_login_staff_bypass", "User", "logged_in", True, False),
            ("impersonated_logout_staff_bypass", "User", "logged_out", True, False),
            # Normal activities still not restricted
            ("normal_login", "User", "logged_in", False, False),
            ("feature_flag_created", "FeatureFlag", "created", False, False),
        ]
    )
    def test_staff_can_see_restricted_logs_when_allowed(
        self, _name: str, scope: str, activity: str, was_impersonated: bool, expected_restricted: bool
    ) -> None:
        log = ActivityLog(
            team_id=self.team.id,
            scope=scope,
            activity=activity,
            was_impersonated=was_impersonated,
        )
        assert activity_visibility_manager.is_restricted(log, restrict_for_staff=False) == expected_restricted

    def test_queryset_excludes_restricted_logs_for_non_staff(self) -> None:
        # Create a mix of activity logs
        ActivityLog.objects.create(team_id=self.team.id, scope="User", activity="logged_in", was_impersonated=True)
        ActivityLog.objects.create(team_id=self.team.id, scope="User", activity="logged_out", was_impersonated=True)
        ActivityLog.objects.create(team_id=self.team.id, scope="User", activity="logged_in", was_impersonated=False)
        ActivityLog.objects.create(
            team_id=self.team.id, scope="FeatureFlag", activity="created", was_impersonated=False
        )

        queryset = ActivityLog.objects.filter(team_id=self.team.id)
        filtered = activity_visibility_manager.apply_to_queryset(queryset, is_staff=False)

        assert queryset.count() == 4
        assert filtered.count() == 2
        assert not filtered.filter(scope="User", activity="logged_in", was_impersonated=True).exists()
        assert not filtered.filter(scope="User", activity="logged_out", was_impersonated=True).exists()
        assert filtered.filter(scope="User", activity="logged_in", was_impersonated=False).exists()
        assert filtered.filter(scope="FeatureFlag", activity="created").exists()

    def test_queryset_includes_all_logs_for_staff(self) -> None:
        ActivityLog.objects.create(team_id=self.team.id, scope="User", activity="logged_in", was_impersonated=True)
        ActivityLog.objects.create(team_id=self.team.id, scope="User", activity="logged_out", was_impersonated=True)
        ActivityLog.objects.create(
            team_id=self.team.id, scope="FeatureFlag", activity="created", was_impersonated=False
        )

        queryset = ActivityLog.objects.filter(team_id=self.team.id)
        filtered = activity_visibility_manager.apply_to_queryset(queryset, is_staff=True)

        assert filtered.count() == 3
