from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import OrganizationMembership
from posthog.models.activity_logging.activity_log import ActivityLog


class TestProductEnablementAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # The endpoint's admin-gated recipes (conversations, replay masking) need an admin caller;
        # the member-denial path is covered by test_admin_gated_products_require_project_admin.
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/product_enablement/"

    def _enable(self, products: list[str], **kwargs):
        return self.client.post(self._url(), {"products": products}, format="json", **kwargs)

    def test_enables_session_replay_with_masking_floor(self):
        response = self._enable(["session_replay"])
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"results": {"session_replay": "enabled"}})

        self.team.refresh_from_db()
        self.assertTrue(self.team.session_recording_opt_in)
        self.assertEqual(self.team.session_recording_masking_config, {"maskAllInputs": True})

    def test_does_not_clobber_existing_masking_config(self):
        self.team.session_recording_masking_config = {"maskAllInputs": False, "maskTextSelector": "*"}
        self.team.save()

        self._enable(["session_replay"])

        self.team.refresh_from_db()
        self.assertTrue(self.team.session_recording_opt_in)
        # The user's deliberate config is left untouched.
        self.assertEqual(
            self.team.session_recording_masking_config,
            {"maskAllInputs": False, "maskTextSelector": "*"},
        )

    def test_enables_error_tracking(self):
        response = self._enable(["error_tracking"])
        self.assertEqual(response.json(), {"results": {"error_tracking": "enabled"}})

        self.team.refresh_from_db()
        self.assertTrue(self.team.autocapture_exceptions_opt_in)

    def test_enables_conversations_mints_token_but_leaves_widget_off(self):
        response = self._enable(["conversations"])
        self.assertEqual(response.json(), {"results": {"conversations": "enabled"}})

        self.team.refresh_from_db()
        self.assertTrue(self.team.conversations_enabled)
        self.assertTrue((self.team.conversations_settings or {}).get("widget_public_token"))
        # The embeddable widget stays off until a channel is connected (a report CTA).
        self.assertFalse((self.team.conversations_settings or {}).get("widget_enabled"))

    def test_already_enabled_is_idempotent(self):
        self.team.session_recording_opt_in = True
        self.team.session_recording_masking_config = {"maskAllInputs": True}
        self.team.save()

        response = self._enable(["session_replay"])
        self.assertEqual(response.json(), {"results": {"session_replay": "already_enabled"}})

    def test_multiple_products_deduped(self):
        response = self._enable(["session_replay", "error_tracking", "session_replay"])
        self.assertEqual(
            response.json(),
            {"results": {"session_replay": "enabled", "error_tracking": "enabled"}},
        )

        self.team.refresh_from_db()
        self.assertTrue(self.team.session_recording_opt_in)
        self.assertTrue(self.team.autocapture_exceptions_opt_in)

    def test_rejects_unknown_product(self):
        response = self._enable(["heatmaps"])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_empty_products(self):
        response = self._enable([])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_admin_gated_products_require_project_admin(self):
        # A non-admin member can enable member-safe products but not the admin-gated ones
        # (conversations / replay masking), matching the team-update API's gate.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        self.assertEqual(self._enable(["error_tracking"]).status_code, status.HTTP_200_OK)
        self.team.refresh_from_db()
        self.assertTrue(self.team.autocapture_exceptions_opt_in)

        response = self._enable(["conversations"])
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.team.refresh_from_db()
        self.assertFalse(self.team.conversations_enabled)

    def test_requires_product_enablement_write_scope(self):
        self.client.logout()

        ok_key = self.create_personal_api_key_with_scopes(["product_enablement:write"])
        response = self._enable(["error_tracking"], HTTP_AUTHORIZATION=f"Bearer {ok_key}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        wrong_key = self.create_personal_api_key_with_scopes(["session_recording:read"])
        response = self._enable(["error_tracking"], HTTP_AUTHORIZATION=f"Bearer {wrong_key}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_enable_writes_activity_log_without_conversations_token(self):
        self._enable(["error_tracking", "conversations"])

        log = ActivityLog.objects.filter(scope="Team", team_id=self.team.id, activity="updated").latest("created_at")
        assert log.detail is not None
        changed_fields = {change["field"] for change in log.detail["changes"]}
        self.assertIn("autocapture_exceptions_opt_in", changed_fields)
        self.assertIn("conversations_enabled", changed_fields)
        # The minted widget token must never land in the audit log.
        self.assertNotIn("conversations_settings", changed_fields)
