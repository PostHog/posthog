from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.activity_logging.utils import activity_storage
from posthog.models.oauth import OAuthApplication
from posthog.models.organization import Organization


class TestOAuthApplicationActivityLogging(BaseTest):
    def setUp(self):
        super().setUp()
        activity_storage.set_user(self.user)

    def tearDown(self):
        activity_storage.clear_all()
        super().tearDown()

    def _create_application(self, scopes: list[str] | None = None, **overrides) -> OAuthApplication:
        defaults = {
            "name": "Test App",
            "client_secret": "test_client_secret",
            "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
            "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
            "redirect_uris": "https://example.com/callback",
            "organization": self.organization,
            "algorithm": "RS256",
            "scopes": scopes or [],
        }
        defaults.update(overrides)
        return OAuthApplication.objects.create(**defaults)

    def _scope_logs(self, application: OAuthApplication, activity: str | None = None):
        logs = ActivityLog.objects.filter(scope="OAuthApplication", item_id=str(application.pk))
        if activity:
            logs = logs.filter(activity=activity)
        return logs

    def test_creating_application_with_scopes_logs_created_activity(self):
        application = self._create_application(scopes=["insight:read"])

        log = self._scope_logs(application, "created").first()
        assert log is not None
        self.assertEqual(log.organization_id, self.organization.id)
        self.assertIsNone(log.team_id)
        self.assertEqual(log.user, self.user)
        self.assertFalse(log.is_system)
        assert log.detail is not None
        self.assertEqual(log.detail["name"], "Test App")
        self.assertEqual(
            log.detail["changes"],
            [
                {
                    "type": "OAuthApplication",
                    "action": "created",
                    "field": "scopes",
                    "before": None,
                    "after": ["insight:read"],
                }
            ],
        )

    def test_creating_application_without_scopes_logs_nothing(self):
        application = self._create_application(scopes=[])

        self.assertEqual(self._scope_logs(application).count(), 0)

    @parameterized.expand(
        [
            ("widened", ["insight:read"], ["insight:read", "llm_gateway:read"], "changed"),
            ("narrowed", ["insight:read", "llm_gateway:read"], ["insight:read"], "changed"),
            ("ceiling_set", [], ["llm_gateway:read"], "created"),
            ("ceiling_removed", ["llm_gateway:read"], [], "deleted"),
        ]
    )
    def test_scopes_change_logs_updated_activity_with_old_and_new_values(
        self, _name: str, before_scopes: list[str], after_scopes: list[str], expected_action: str
    ):
        application = self._create_application(scopes=before_scopes)
        self._scope_logs(application).delete()

        application.scopes = after_scopes
        application.save()

        log = self._scope_logs(application, "updated").first()
        assert log is not None
        assert log.detail is not None
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.organization_id, self.organization.id)

        changes = log.detail["changes"]
        self.assertEqual(len(changes), 1)
        change = changes[0]
        self.assertEqual(change["field"], "scopes")
        self.assertEqual(change["action"], expected_action)
        if expected_action in ("changed", "deleted"):
            self.assertEqual(change["before"], before_scopes)
        if expected_action in ("changed", "created"):
            self.assertEqual(change["after"], after_scopes)

    def test_non_scope_changes_log_nothing(self):
        application = self._create_application(scopes=["insight:read"])
        self._scope_logs(application).delete()

        application.name = "Renamed App"
        application.save()

        self.assertEqual(self._scope_logs(application).count(), 0)

    def test_only_scopes_change_appears_when_other_fields_change_in_same_save(self):
        application = self._create_application(scopes=["insight:read"])
        self._scope_logs(application).delete()

        application.name = "Renamed App"
        application.client_secret = "new_secret_value"
        application.scopes = ["insight:read", "insight:write"]
        application.save()

        log = self._scope_logs(application, "updated").first()
        assert log is not None
        assert log.detail is not None
        fields = [change["field"] for change in log.detail["changes"]]
        self.assertEqual(fields, ["scopes"])
        self.assertNotIn("new_secret_value", str(log.detail))

    def test_scope_reorder_logs_nothing(self):
        application = self._create_application(scopes=["insight:read", "query:read"])
        self._scope_logs(application).delete()

        application.scopes = ["query:read", "insight:read"]
        application.save()

        self.assertEqual(self._scope_logs(application).count(), 0)

    def test_save_with_update_fields_excluding_scopes_logs_nothing(self):
        application = self._create_application(scopes=["insight:read"])
        self._scope_logs(application).delete()

        application.provisioning_active = True
        application.save(update_fields=["provisioning_active"])

        self.assertEqual(self._scope_logs(application).count(), 0)

    def test_save_with_update_fields_including_scopes_logs_change(self):
        application = self._create_application(scopes=["insight:read"])
        self._scope_logs(application).delete()

        application.scopes = ["insight:read", "query:read"]
        application.save(update_fields=["scopes"])

        self.assertEqual(self._scope_logs(application, "updated").count(), 1)

    def test_system_change_without_user_is_logged_as_system(self):
        application = self._create_application(scopes=["insight:read"], is_cimd_client=True)
        self._scope_logs(application).delete()
        activity_storage.clear_user()

        application.scopes = ["insight:read", "query:read"]
        application.save()

        log = self._scope_logs(application, "updated").first()
        assert log is not None
        self.assertIsNone(log.user)
        self.assertTrue(log.is_system)
        assert log.detail is not None
        self.assertTrue(log.detail["context"]["is_cimd_client"])

    def test_impersonated_change_is_flagged(self):
        application = self._create_application(scopes=["insight:read"])
        self._scope_logs(application).delete()
        activity_storage.set_was_impersonated(True)

        application.scopes = ["insight:read", "query:read"]
        application.save()

        log = self._scope_logs(application, "updated").first()
        assert log is not None
        self.assertTrue(log.was_impersonated)

    def test_context_captures_client_id_and_registration_channel(self):
        application = self._create_application(
            scopes=["insight:read"], is_dcr_client=True, is_first_party=False, client_id="test_client_id_123"
        )

        log = self._scope_logs(application, "created").first()
        assert log is not None
        assert log.detail is not None
        context = log.detail["context"]
        self.assertEqual(context["client_id"], "test_client_id_123")
        self.assertEqual(log.detail["name"], "Test App")
        self.assertTrue(context["is_dcr_client"])
        self.assertFalse(context["is_cimd_client"])
        self.assertFalse(context["is_first_party"])

    def test_orgless_application_falls_back_to_acting_users_organization(self):
        application = self._create_application(scopes=["insight:read"], organization=None)

        log = self._scope_logs(application, "created").first()
        assert log is not None
        self.assertEqual(log.organization_id, self.organization.id)

    def test_orgless_application_without_user_is_skipped_without_error(self):
        activity_storage.clear_user()

        application = self._create_application(scopes=["insight:read"], organization=None)

        self.assertEqual(self._scope_logs(application).count(), 0)

    def test_application_org_takes_precedence_over_acting_users_organization(self):
        other_organization = Organization.objects.create(name="Other Org")
        application = self._create_application(scopes=["insight:read"], organization=other_organization)

        log = self._scope_logs(application, "created").first()
        assert log is not None
        self.assertEqual(log.organization_id, other_organization.id)
