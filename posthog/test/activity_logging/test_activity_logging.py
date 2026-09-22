from datetime import timedelta
from uuid import UUID

import pytest
from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.db.utils import IntegrityError
from django.utils import timezone

from parameterized import parameterized

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityLog, Change, Detail, Trigger, log_activity
from posthog.models.activity_logging.model_activity import ActivityTriggerContext
from posthog.models.activity_logging.utils import activity_storage, activity_visibility_manager
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken
from posthog.models.scoping import team_scope
from posthog.models.utils import UUIDT
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

from products.dashboards.backend.models.dashboard_widget import DashboardWidget


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
        assert log.detail is not None
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

    def test_client_is_populated_from_activity_storage(self) -> None:
        activity_storage.set_client("posthog-js/1.234.0")
        try:
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team.id,
                user=self.user,
                was_impersonated=False,
                item_id=7,
                scope="FeatureFlag",
                activity="created",
                detail=Detail(),
            )
        finally:
            activity_storage.clear_client()

        log: ActivityLog = ActivityLog.objects.latest("id")
        self.assertEqual(log.client, "posthog-js/1.234.0")

    def test_explicit_client_overrides_storage(self) -> None:
        activity_storage.set_client("storage-client")
        try:
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team.id,
                user=self.user,
                was_impersonated=False,
                item_id=8,
                scope="FeatureFlag",
                activity="created",
                detail=Detail(),
                client="explicit-client",
            )
        finally:
            activity_storage.clear_client()

        log: ActivityLog = ActivityLog.objects.latest("id")
        self.assertEqual(log.client, "explicit-client")

    def test_client_defaults_to_none_when_unset(self) -> None:
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=self.user,
            was_impersonated=False,
            item_id=9,
            scope="FeatureFlag",
            activity="created",
            detail=Detail(),
        )
        log: ActivityLog = ActivityLog.objects.latest("id")
        self.assertIsNone(log.client)

    def test_agent_intent_and_task_id_fill_the_trigger(self) -> None:
        task_id = "019f4c2a-0000-7000-8000-0000000000aa"
        activity_storage.set_agent_intent("Repairing a tile that hit the query row limit")
        activity_storage.set_agent_task_id(task_id)
        try:
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team.id,
                user=self.user,
                was_impersonated=False,
                item_id=20,
                scope="Dashboard",
                activity="created",
                detail=Detail(),
            )
        finally:
            activity_storage.clear_agent_intent()
            activity_storage.clear_agent_task_id()

        log: ActivityLog = ActivityLog.objects.latest("id")
        assert log.detail is not None
        self.assertEqual(
            log.detail["trigger"],
            {
                "job_type": "agent",
                "job_id": task_id,
                "payload": {"intent": "Repairing a tile that hit the query row limit"},
            },
        )

    def test_agent_intent_does_not_clobber_a_product_trigger(self) -> None:
        product_trigger = Trigger(job_type="hog_flow", job_id="4321", payload={})
        activity_storage.set_agent_intent("Renaming the tile the user pointed at")
        activity_storage.set_agent_task_id("019f4c2a-0000-7000-8000-0000000000bb")
        try:
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team.id,
                user=self.user,
                was_impersonated=False,
                item_id=21,
                scope="Dashboard",
                activity="created",
                detail=Detail(trigger=product_trigger),
            )
        finally:
            activity_storage.clear_agent_intent()
            activity_storage.clear_agent_task_id()

        log: ActivityLog = ActivityLog.objects.latest("id")
        assert log.detail is not None
        self.assertEqual(log.detail["trigger"]["job_type"], "hog_flow")

    def test_an_intent_without_a_task_binding_writes_no_task_id(self) -> None:
        activity_storage.set_agent_intent("Disabling the flag per an incident runbook")
        try:
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team.id,
                user=self.user,
                was_impersonated=False,
                item_id=23,
                scope="Dashboard",
                activity="created",
                detail=Detail(),
            )
        finally:
            activity_storage.clear_agent_intent()

        log: ActivityLog = ActivityLog.objects.latest("id")
        assert log.detail is not None
        self.assertEqual(
            log.detail["trigger"],
            {
                "job_type": "agent",
                "job_id": "",
                "payload": {"intent": "Disabling the flag per an incident runbook"},
            },
        )

    def test_a_failing_agent_trigger_still_writes_the_row(self) -> None:
        with patch(
            "posthog.models.activity_logging.activity_log.agent_trigger", side_effect=RuntimeError("storage is broken")
        ):
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team.id,
                user=self.user,
                was_impersonated=False,
                item_id=24,
                scope="Dashboard",
                activity="created",
                detail=Detail(),
            )

        log: ActivityLog = ActivityLog.objects.latest("id")
        self.assertEqual(log.item_id, "24")
        assert log.detail is not None
        self.assertIsNone(log.detail["trigger"])

    def test_trigger_stays_unset_without_agent_context(self) -> None:
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=self.user,
            was_impersonated=False,
            item_id=22,
            scope="Dashboard",
            activity="created",
            detail=Detail(),
        )
        log: ActivityLog = ActivityLog.objects.latest("id")
        assert log.detail is not None
        self.assertIsNone(log.detail["trigger"])

    def test_ip_address_is_populated_from_activity_storage(self) -> None:
        activity_storage.set_ip_address("203.0.113.42")
        try:
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team.id,
                user=self.user,
                was_impersonated=False,
                item_id=10,
                scope="FeatureFlag",
                activity="created",
                detail=Detail(),
            )
        finally:
            activity_storage.clear_ip_address()

        log: ActivityLog = ActivityLog.objects.latest("id")
        self.assertEqual(log.ip_address, "203.0.113.42")

    def test_explicit_ip_address_overrides_storage(self) -> None:
        activity_storage.set_ip_address("10.0.0.1")
        try:
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team.id,
                user=self.user,
                was_impersonated=False,
                item_id=11,
                scope="FeatureFlag",
                activity="created",
                detail=Detail(),
                ip_address="198.51.100.7",
            )
        finally:
            activity_storage.clear_ip_address()

        log: ActivityLog = ActivityLog.objects.latest("id")
        self.assertEqual(log.ip_address, "198.51.100.7")

    def test_ip_address_defaults_to_none_when_unset(self) -> None:
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=self.user,
            was_impersonated=False,
            item_id=12,
            scope="FeatureFlag",
            activity="created",
            detail=Detail(),
        )
        log: ActivityLog = ActivityLog.objects.latest("id")
        self.assertIsNone(log.ip_address)

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

    def test_deferred_write_failure_does_not_escape_committed_transaction(self) -> None:
        # A write deferred to transaction.on_commit runs after the transaction commits, so a
        # failure there must not surface as a request error for data that already persisted.
        with patch("posthog.models.activity_logging.activity_log.logger") as mock_logger:
            with self.settings(TEST=False, ACTIVITY_LOG_TRANSACTION_MANAGEMENT=True):
                with patch.object(ActivityLog.objects, "create", side_effect=IntegrityError("write timed out")):
                    try:
                        with self.captureOnCommitCallbacks(execute=True):
                            log_activity(
                                organization_id=self.organization.id,
                                team_id=self.team.id,
                                user=self.user,
                                was_impersonated=False,
                                item_id="12345",
                                scope="FeatureFlag",
                                activity="updated",
                                detail=Detail(changes=[Change(type="FeatureFlag", field="active", action="created")]),
                            )
                    except Exception as e:
                        raise pytest.fail(f"Deferred write failure should not escape: {e}")

            warning = mock_logger.warn.call_args
            self.assertEqual(warning.args[0], "activity_log.failed_to_write_to_activity_log")
            self.assertIsInstance(warning.kwargs["exception"], IntegrityError)

    def test_does_not_throw_if_cannot_log_activity(self) -> None:
        # Assert on the module logger directly instead of assertLogs: the root logger sits at
        # ERROR under test settings, so whether the warning reaches a root handler depends on
        # global logging state other tests may have touched
        with patch("posthog.models.activity_logging.activity_log.logger") as mock_logger:
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

            warning = mock_logger.warn.call_args
            self.assertIsNotNone(warning)
            self.assertEqual(warning.args[0], "activity_log.failed_to_write_to_activity_log")
            self.assertEqual(warning.kwargs["scope"], "testing throwing exceptions on create")
            self.assertEqual(warning.kwargs["team"], 1)
            self.assertEqual(warning.kwargs["activity"], "does not explode")
            self.assertIsInstance(warning.kwargs["exception"], ValueError)


class TestModelActivityMixinTeamScoping(BaseTest):
    def test_update_outside_team_scope_still_logs_the_change(self) -> None:
        # DashboardWidget reads through a fail-closed manager, and a save from a Celery task or a
        # management command carries no team context for it to read the before-state with.
        with team_scope(self.team.id):
            widget = DashboardWidget.objects.create(team=self.team, widget_type="insight", name="Weekly signups")

        widget.name = "Monthly signups"
        widget.save()

        log: ActivityLog = ActivityLog.objects.filter(
            scope="DashboardWidget", item_id=str(widget.id), activity="updated"
        ).latest("id")
        assert log.detail is not None
        self.assertIn("name", [change["field"] for change in log.detail["changes"]])


class TestActivityLogVisibilityManager(BaseTest):
    @parameterized.expand(
        [
            # User login/logout - only impersonated sessions are restricted
            ("impersonated_login", "User", "logged_in", True, True),
            ("impersonated_logout", "User", "logged_out", True, True),
            ("normal_login", "User", "logged_in", False, False),
            ("normal_logout", "User", "logged_out", False, False),
            # User create/update - always restricted (regardless of impersonation)
            ("user_updated", "User", "updated", True, True),
            ("user_updated_not_impersonated", "User", "updated", False, True),
            ("user_created", "User", "created", False, True),
            # User activities not in the restricted list are not restricted
            ("user_changed_password", "User", "changed_password", False, False),
            # InstanceSetting updates are staff-only and must be hidden from non-staff viewers
            ("instance_setting_updated", "InstanceSetting", "updated", False, True),
            # AI-gateway top-ups are staff-only and must be hidden from non-staff viewers
            ("ai_gateway_credit_added", "AIGatewayCredit", "credit_added", False, True),
            # Ticket comment rows reference support-ticket bodies (rows written before write-time
            # masking still hold plaintext) and must be hidden from non-staff viewers
            ("ticket_comment", "Ticket", "commented", False, True),
            ("ticket_task_comment", "Ticket", "created task", False, True),
            ("conversations_ticket_comment", "conversations_ticket", "commented", False, True),
            ("conversations_ticket_task_comment", "conversations_ticket", "created task", False, True),
            # Ticket lifecycle activities stay visible — only comment rows are hidden
            ("ticket_updated", "Ticket", "updated", False, False),
            # Non-User scopes are unaffected
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
        self.assertEqual(activity_visibility_manager.is_restricted(log, restrict_for_staff=True), expected_restricted)

    @parameterized.expand(
        [
            # Staff can see all User activities (via allow_staff=True)
            ("impersonated_login_staff_bypass", "User", "logged_in", True, False),
            ("impersonated_logout_staff_bypass", "User", "logged_out", True, False),
            ("normal_login_staff_bypass", "User", "logged_in", False, False),
            ("user_updated_staff_bypass", "User", "updated", False, False),
            ("user_created_staff_bypass", "User", "created", False, False),
            # Staff can also see InstanceSetting updates (allow_staff=True)
            ("instance_setting_updated_staff_bypass", "InstanceSetting", "updated", False, False),
            # Staff can also see AI-gateway top-ups (allow_staff=True)
            ("ai_gateway_credit_added_staff_bypass", "AIGatewayCredit", "credit_added", False, False),
            # Staff can also see ticket comment rows (allow_staff=True)
            ("ticket_comment_staff_bypass", "Ticket", "commented", False, False),
            ("conversations_ticket_comment_staff_bypass", "conversations_ticket", "commented", False, False),
            # Non-User activities still not restricted for anyone
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
        self.assertEqual(activity_visibility_manager.is_restricted(log, restrict_for_staff=False), expected_restricted)

    def test_queryset_excludes_restricted_logs_for_non_staff(self) -> None:
        # Create a mix of activity logs
        ActivityLog.objects.create(team_id=self.team.id, scope="User", activity="logged_in", was_impersonated=True)
        ActivityLog.objects.create(team_id=self.team.id, scope="User", activity="logged_out", was_impersonated=True)
        ActivityLog.objects.create(team_id=self.team.id, scope="User", activity="logged_in", was_impersonated=False)
        ActivityLog.objects.create(team_id=self.team.id, scope="User", activity="updated", was_impersonated=False)
        ActivityLog.objects.create(
            team_id=self.team.id, scope="FeatureFlag", activity="created", was_impersonated=False
        )

        queryset = ActivityLog.objects.filter(team_id=self.team.id)
        filtered = activity_visibility_manager.apply_to_queryset(queryset, is_staff=False)

        # Impersonated logins and user updates should be filtered, but normal logins should remain
        self.assertEqual(queryset.count(), 5)
        self.assertEqual(filtered.count(), 2)  # normal login + feature flag
        self.assertTrue(filtered.filter(scope="User", activity="logged_in", was_impersonated=False).exists())
        self.assertFalse(filtered.filter(scope="User", activity="logged_in", was_impersonated=True).exists())
        self.assertFalse(filtered.filter(scope="User", activity="updated").exists())
        self.assertTrue(filtered.filter(scope="FeatureFlag", activity="created").exists())

    def test_queryset_excludes_ai_gateway_credit_for_non_staff(self) -> None:
        # Pin the actual API-facing exclusion path (apply_to_queryset), not just is_restricted:
        # the staff email, credit reason, and balance must stay out of org-scoped endpoints.
        ActivityLog.objects.create(team_id=self.team.id, scope="AIGatewayCredit", activity="credit_added")
        ActivityLog.objects.create(team_id=self.team.id, scope="FeatureFlag", activity="created")
        queryset = ActivityLog.objects.filter(team_id=self.team.id)

        non_staff = activity_visibility_manager.apply_to_queryset(queryset, is_staff=False)
        assert not non_staff.filter(scope="AIGatewayCredit").exists()
        assert non_staff.filter(scope="FeatureFlag").exists()

        staff = activity_visibility_manager.apply_to_queryset(queryset, is_staff=True)
        assert staff.filter(scope="AIGatewayCredit").exists()

    def test_queryset_excludes_ticket_comment_rows_for_non_staff(self) -> None:
        # Pin the API-facing exclusion path: ticket comment rows written before write-time masking
        # hold plaintext ticket bodies, so they must not come back through activity log endpoints.
        # Ticket lifecycle rows stay visible.
        ActivityLog.objects.create(
            team_id=self.team.id,
            scope="conversations_ticket",
            activity="commented",
            detail={"changes": [{"type": "Comment", "field": "content", "action": "created", "after": "plaintext"}]},
        )
        ActivityLog.objects.create(team_id=self.team.id, scope="Ticket", activity="commented")
        ActivityLog.objects.create(team_id=self.team.id, scope="Ticket", activity="updated")
        queryset = ActivityLog.objects.filter(team_id=self.team.id)

        non_staff = activity_visibility_manager.apply_to_queryset(queryset, is_staff=False)
        assert not non_staff.filter(scope="conversations_ticket", activity="commented").exists()
        assert not non_staff.filter(scope="Ticket", activity="commented").exists()
        assert non_staff.filter(scope="Ticket", activity="updated").exists()

        staff = activity_visibility_manager.apply_to_queryset(queryset, is_staff=True)
        assert staff.filter(scope="conversations_ticket", activity="commented").exists()

    def test_queryset_includes_all_logs_for_staff(self) -> None:
        ActivityLog.objects.create(team_id=self.team.id, scope="User", activity="logged_in", was_impersonated=True)
        ActivityLog.objects.create(team_id=self.team.id, scope="User", activity="logged_out", was_impersonated=True)
        ActivityLog.objects.create(team_id=self.team.id, scope="User", activity="updated", was_impersonated=False)
        ActivityLog.objects.create(
            team_id=self.team.id, scope="FeatureFlag", activity="created", was_impersonated=False
        )

        queryset = ActivityLog.objects.filter(team_id=self.team.id)
        filtered = activity_visibility_manager.apply_to_queryset(queryset, is_staff=True)

        self.assertEqual(filtered.count(), 4)


class TestActivityTriggerContext(BaseTest):
    def tearDown(self):
        activity_storage.clear_trigger()
        super().tearDown()

    def test_nested_contexts_restore_the_outer_trigger(self):
        outer = Trigger(job_type="hog_flow", job_id="outer", payload={})
        inner = Trigger(job_type="hog_flow", job_id="inner", payload={})

        with ActivityTriggerContext(outer):
            with ActivityTriggerContext(inner):
                self.assertEqual(activity_storage.get_trigger(), inner)
            self.assertEqual(activity_storage.get_trigger(), outer)
        self.assertIsNone(activity_storage.get_trigger())

    def test_none_trigger_is_a_noop(self):
        outer = Trigger(job_type="hog_flow", job_id="outer", payload={})
        with ActivityTriggerContext(outer):
            with ActivityTriggerContext(None):
                self.assertEqual(activity_storage.get_trigger(), outer)
            self.assertEqual(activity_storage.get_trigger(), outer)


class TestAgentAttributionOnApiWrites(APIBaseTest):
    """The intent header, the OAuth token binding and the audit row only meet on a real request."""

    def _authenticate_as_oauth_agent(
        self, client_id: str, task_id: UUID | None, delegated: bool = False
    ) -> OAuthAccessToken:
        application = OAuthApplication.objects.create(
            name="OAuth application",
            client_id=client_id,
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token="pha_sandbox_agent",
            scope="dashboard:read dashboard:write",
            expires=timezone.now() + timedelta(hours=1),
            scoped_teams=[self.team.id],
            sandbox_task_id=task_id,
        )
        self.client.logout()
        token_value = token.token
        if delegated:
            token_value = encode_jwt(
                {"id": self.user.id, "oauth_access_token_id": str(token.id)},
                timedelta(minutes=15),
                PosthogJwtAudience.DELEGATED_USER,
            )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_value}")
        return token

    @parameterized.expand(
        [
            (
                "records an allowlisted token bound to a sandbox task",
                ARRAY_APP_CLIENT_ID_DEV,
                UUID("019f4c2a-0000-7000-8000-0000000000aa"),
                False,
                "Repairing a tile that hit the query row limit",
                {
                    "job_type": "agent",
                    "job_id": "019f4c2a-0000-7000-8000-0000000000aa",
                    "payload": {"intent": "Repairing a tile that hit the query row limit"},
                },
            ),
            (
                "records a third-party delegated token bound to a sandbox task",
                "third-party-client",
                UUID("019f4c2a-0000-7000-8000-0000000000aa"),
                True,
                "Repairing a tile that hit the query row limit",
                {
                    "job_type": "agent",
                    "job_id": "019f4c2a-0000-7000-8000-0000000000aa",
                    "payload": {"intent": "Repairing a tile that hit the query row limit"},
                },
            ),
            (
                "ignores unbound Array intent without consent lineage",
                ARRAY_APP_CLIENT_ID_DEV,
                None,
                False,
                "Repairing a tile that hit the query row limit",
                None,
            ),
            (
                "ignores unbound delegated Array intent without consent lineage",
                ARRAY_APP_CLIENT_ID_DEV,
                None,
                True,
                "Repairing a tile that hit the query row limit",
                None,
            ),
            (
                "ignores third-party intent without a task binding",
                "third-party-client",
                None,
                False,
                "Repairing a tile that hit the query row limit",
                None,
            ),
            (
                "ignores third-party delegated intent without a task binding",
                "third-party-client",
                None,
                True,
                "Repairing a tile that hit the query row limit",
                None,
            ),
            ("ignores an empty allowlisted intent", ARRAY_APP_CLIENT_ID_DEV, None, False, None, None),
            (
                "records an allowlisted task binding without intent",
                ARRAY_APP_CLIENT_ID_DEV,
                UUID("019f4c2a-0000-7000-8000-0000000000aa"),
                False,
                None,
                {
                    "job_type": "agent",
                    "job_id": "019f4c2a-0000-7000-8000-0000000000aa",
                    "payload": {},
                },
            ),
        ]
    )
    def test_agent_write(
        self,
        _name: str,
        client_id: str,
        task_id: UUID | None,
        delegated: bool,
        intent: str | None,
        expected_trigger: dict | None,
    ) -> None:
        self._authenticate_as_oauth_agent(client_id, task_id, delegated)

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/",
            {"name": "Weekly signups"},
            HTTP_X_POSTHOG_CLIENT="mcp",
            HTTP_X_POSTHOG_TASK_ID="019f4c2a-0000-7000-8000-0000000000bb",
            HTTP_X_POSTHOG_INTENT=intent or "",
        )
        self.assertEqual(response.status_code, 201, response.content)

        log = ActivityLog.objects.filter(scope="Dashboard").latest("id")
        assert log.detail is not None
        self.assertEqual(log.detail["trigger"], expected_trigger)
        self.assertEqual(log.user_id, self.user.id)
        self.assertEqual(log.client, "mcp")

    def test_records_intent_from_an_interactive_desktop_grant(self) -> None:
        token = self._authenticate_as_oauth_agent(ARRAY_APP_CLIENT_ID_DEV, None)
        OAuthRefreshToken.objects.create(
            user=self.user,
            application=token.application,
            token="refresh-token",
            access_token=token,
            scoped_teams=[self.team.id],
            scoped_organizations=[],
        )

        with (
            patch.object(
                OAuthAccessTokenAuthentication,
                "_validate_token",
                autospec=True,
                side_effect=OAuthAccessTokenAuthentication._validate_token,
            ) as validate_token,
            patch("posthog.auth.capture_exception") as capture_exception,
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/dashboards/",
                {"name": "Weekly signups"},
                HTTP_X_POSTHOG_INTENT="Repairing a tile that hit the query row limit",
            )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(validate_token.call_count, 1)
        capture_exception.assert_not_called()
        log = ActivityLog.objects.filter(scope="Dashboard").latest("id")
        assert log.detail is not None
        self.assertEqual(
            log.detail["trigger"],
            {"job_type": "agent", "job_id": "", "payload": {"intent": "Repairing a tile that hit the query row limit"}},
        )

    def test_a_failing_attribution_loses_the_intent_and_nothing_else(self) -> None:
        task_id = UUID("019f4c2a-0000-7000-8000-0000000000aa")
        self._authenticate_as_oauth_agent(ARRAY_APP_CLIENT_ID_DEV, task_id)

        with patch("posthog.auth.activity_storage.set_agent_intent", side_effect=RuntimeError("storage is broken")):
            response = self.client.post(
                f"/api/projects/{self.team.id}/dashboards/",
                {"name": "Weekly signups"},
                HTTP_X_POSTHOG_INTENT="Repairing a tile that hit the query row limit",
            )

        self.assertEqual(response.status_code, 201, response.content)
        log = ActivityLog.objects.filter(scope="Dashboard").latest("id")
        assert log.detail is not None
        self.assertEqual(log.detail["trigger"], {"job_type": "agent", "job_id": str(task_id), "payload": {}})
