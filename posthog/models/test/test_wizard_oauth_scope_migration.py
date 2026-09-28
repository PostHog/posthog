from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.db import connection
from django.test import TestCase, override_settings

from posthog.models.oauth import OAuthApplication
from posthog.scopes import clamp_scopes_to_ceiling


@override_settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID="cloud-wizard-client")
class TestWizardOAuthScopeMigration(TestCase):
    def test_adds_wizard_run_write_to_cli_and_cloud_apps_once(self) -> None:
        migration = import_module("posthog.migrations.1387_add_wizard_run_scope_to_wizard_oauth_app")
        apps_to_update = [
            OAuthApplication.objects.create(
                name="PostHog Wizard",
                client_id=client_id,
                client_type=OAuthApplication.CLIENT_PUBLIC,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="http://localhost/callback",
                algorithm="RS256",
                scopes=["@default", "wizard_session:write"],
            )
            for client_id in (*migration.WIZARD_CLI_CLIENT_IDS, "cloud-wizard-client")
        ]
        unrelated_app = OAuthApplication.objects.create(
            name="Other app",
            client_id="other-client",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost/callback",
            algorithm="RS256",
            scopes=["@default"],
        )
        schema_editor = SimpleNamespace(connection=connection)

        migration.add_wizard_run_scope(apps, schema_editor)
        migration.add_wizard_run_scope(apps, schema_editor)

        for app in apps_to_update:
            app.refresh_from_db()
            assert app.scopes == ["@default", "wizard_session:write", "wizard_run:write"]
            assert clamp_scopes_to_ceiling(["wizard_run:write"], app.ceiling_scopes) == ["wizard_run:write"]
        unrelated_app.refresh_from_db()
        assert unrelated_app.scopes == ["@default"]
