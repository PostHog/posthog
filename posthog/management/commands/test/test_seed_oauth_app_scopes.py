from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from posthog.models.oauth import OAuthApplication


class TestSeedOAuthAppScopes(BaseTest):
    def _create_app(
        self,
        client_id: str = "seed_test_client",
        scopes: list[str] | None = None,
        optional_scopes: list[str] | None = None,
    ) -> OAuthApplication:
        return OAuthApplication.objects.create(
            name="Seed test app",
            client_id=client_id,
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://localhost",
            algorithm="RS256",
            organization=self.organization,
            scopes=scopes if scopes is not None else [],
            optional_scopes=optional_scopes if optional_scopes is not None else [],
        )

    def _run(self, **kwargs: str | bool) -> str:
        out = StringIO()
        call_command("seed_oauth_app_scopes", stdout=out, **kwargs)
        return out.getvalue()

    def test_happy_path_sets_scopes(self):
        app = self._create_app()
        output = self._run(client_id="seed_test_client", scopes="@default,llm_gateway:read")

        app.refresh_from_db()
        assert app.scopes == ["@default", "llm_gateway:read"]
        assert "Seeded Seed test app scopes to ['@default', 'llm_gateway:read']" in output
        assert "privileged in ceiling: ['llm_gateway:read']" in output
        assert "hidden in ceiling:     none" in output

    def test_existing_optional_scopes_block_seed_without_flag(self):
        app = self._create_app(scopes=["insight:read"], optional_scopes=["dashboard:read"])

        with self.assertRaises(CommandError) as ctx:
            self._run(client_id="seed_test_client", scopes="@default,llm_gateway:read")

        assert "optional_scopes ['dashboard:read']" in str(ctx.exception)
        app.refresh_from_db()
        assert app.scopes == ["insight:read"]
        assert app.optional_scopes == ["dashboard:read"]

    def test_clear_optional_scopes_flag_clears_and_seeds(self):
        app = self._create_app(scopes=["insight:read"], optional_scopes=["dashboard:read"])
        output = self._run(client_id="seed_test_client", scopes="@default,llm_gateway:read", clear_optional_scopes=True)

        app.refresh_from_db()
        assert app.scopes == ["@default", "llm_gateway:read"]
        assert app.optional_scopes == []
        assert "current optional:      ['dashboard:read'] (will clear)" in output

    def test_hidden_scope_surfaced_in_output(self):
        app = self._create_app()
        output = self._run(client_id="seed_test_client", scopes="@default,wizard_session:read")

        app.refresh_from_db()
        assert app.scopes == ["@default", "wizard_session:read"]
        assert "hidden in ceiling:     ['wizard_session:read']" in output

    def test_dedupes_and_preserves_order(self):
        self._create_app()
        self._run(client_id="seed_test_client", scopes=" @default , llm_gateway:read , @default ")

        app = OAuthApplication.objects.get(client_id="seed_test_client")
        assert app.scopes == ["@default", "llm_gateway:read"]

    @parameterized.expand(
        [
            ("default_typo", "@defalt,llm_gateway:read"),
            ("wildcard", "*"),
            ("wildcard_with_default", "@default,*"),
            ("unknown_scope", "@default,not_a_real:scope"),
        ]
    )
    def test_rejects_invalid_entries(self, _name, scopes):
        app = self._create_app(scopes=["insight:read"])

        with self.assertRaises(CommandError):
            self._run(client_id="seed_test_client", scopes=scopes)

        app.refresh_from_db()
        assert app.scopes == ["insight:read"]

    @parameterized.expand([("empty_string", ""), ("only_separators", " , , ")])
    def test_rejects_empty_list(self, _name, scopes):
        app = self._create_app(scopes=["insight:read"])

        with self.assertRaises(CommandError):
            self._run(client_id="seed_test_client", scopes=scopes)

        app.refresh_from_db()
        assert app.scopes == ["insight:read"]

    def test_dry_run_writes_nothing(self):
        app = self._create_app(scopes=["insight:read"])
        output = self._run(client_id="seed_test_client", scopes="@default,llm_gateway:read", dry_run=True)

        app.refresh_from_db()
        assert app.scopes == ["insight:read"]
        assert "Dry run: no changes written." in output
        assert "new scopes:" in output
        assert "effective ceiling:" in output

    def test_missing_client_id_errors(self):
        with self.assertRaises(CommandError):
            self._run(client_id="does_not_exist", scopes="@default")
