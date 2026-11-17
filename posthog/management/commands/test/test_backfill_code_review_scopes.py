from datetime import timedelta

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.utils import timezone

from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken


class TestBackfillCodeReviewScopes(BaseTest):
    def _make_app(self, client_id: str, scopes: list[str], optional_scopes: list[str]) -> OAuthApplication:
        return OAuthApplication.objects.create(
            name=client_id,
            client_id=client_id,
            client_secret=f"{client_id}_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
            scopes=scopes,
            optional_scopes=optional_scopes,
        )

    def _make_token(self, app: OAuthApplication, name: str, scope: str, expires_in: timedelta) -> OAuthAccessToken:
        return OAuthAccessToken.objects.create(
            application=app,
            user=self.user,
            token=f"token_{name}",
            expires=timezone.now() + expires_in,
            scope=scope,
        )

    def test_adds_new_names_to_applications_and_usable_tokens_only(self):
        app = self._make_app("renamed", ["review_hog:read", "query:read"], ["stamphog:write"])
        untouched_app = self._make_app("untouched", ["query:read"], [])
        live = self._make_token(app, "live", "review_hog:read stamphog:write query:read", timedelta(hours=1))
        expired = self._make_token(app, "expired", "review_hog:read", -timedelta(hours=1))
        expired_refreshable = self._make_token(app, "refreshable", "stamphog:read", -timedelta(hours=1))
        OAuthRefreshToken.objects.create(
            application=app, user=self.user, token="refresh_token", access_token=expired_refreshable
        )

        call_command("backfill_code_review_scopes", batch_size=1, sleep_interval=0)

        app.refresh_from_db()
        assert app.scopes == ["review_hog:read", "query:read", "code_review:read"]
        assert app.optional_scopes == ["stamphog:write", "code_review_approval:write"]
        untouched_app.refresh_from_db()
        assert untouched_app.scopes == ["query:read"]
        assert untouched_app.optional_scopes == []

        live.refresh_from_db()
        assert live.scope == "review_hog:read stamphog:write query:read code_review:read code_review_approval:write"
        expired_refreshable.refresh_from_db()
        assert expired_refreshable.scope == "stamphog:read code_review_approval:read"
        expired.refresh_from_db()
        assert expired.scope == "review_hog:read"

    def test_rerun_and_dry_run_change_nothing(self):
        app = self._make_app("rerun", ["review_hog:write", "code_review:write"], [])
        live = self._make_token(app, "rerun", "review_hog:read", timedelta(hours=1))

        call_command("backfill_code_review_scopes", sleep_interval=0, dry_run=True)
        live.refresh_from_db()
        assert live.scope == "review_hog:read"

        call_command("backfill_code_review_scopes", sleep_interval=0)
        call_command("backfill_code_review_scopes", sleep_interval=0)

        app.refresh_from_db()
        assert app.scopes == ["review_hog:write", "code_review:write"]
        live.refresh_from_db()
        assert live.scope == "review_hog:read code_review:read"
