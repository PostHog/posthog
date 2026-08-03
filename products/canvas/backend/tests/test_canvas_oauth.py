from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.utils import timezone

from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.scoping import team_scope

from products.tasks.backend.models import Channel


class TestCanvasOAuthAccess(APIBaseTest):
    """The desktop app reaches /canvases/ exclusively through OAuth bearer tokens,
    a path session-authenticated API tests never exercise. Wildcard covers the
    grandfathered `*` grant; `canvas:read` covers tokens narrowed to an app's
    scope ceiling at grant time (which must include the canvas scope)."""

    def _bearer(self, scope: str) -> str:
        app = OAuthApplication.objects.create(
            name="desktop",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            skip_authorization=False,
            organization=self.organization,
            user=self.user,
        )
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=app,
            token=f"pha_{scope.replace(':', '-').replace('*', 'star')}",
            scope=scope,
            expires=timezone.now() + timedelta(hours=1),
            scoped_teams=[],
            scoped_organizations=[],
        )
        return token.token

    def _list_canvases(self, scope: str) -> int:
        with team_scope(self.team.id):
            channel = Channel.objects.create(team=self.team, name="general")
        token = self._bearer(scope)
        self.client.logout()
        res = self.client.get(
            f"/api/projects/{self.team.id}/canvases/?channel={channel.id}&limit=200",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        return res.status_code

    def test_list_canvases_with_wildcard_oauth_token(self):
        assert self._list_canvases("*") == 200

    def test_list_canvases_with_canvas_read_oauth_token(self):
        assert self._list_canvases("canvas:read") == 200

    def test_list_canvases_denied_without_canvas_scope(self):
        # A token whose enumerated grant predates the canvas scope: other scopes
        # present, canvas absent. This is what a stale desktop session narrowed
        # to an app's scope ceiling looks like; the client's OAUTH_SCOPE_VERSION
        # bump exists to re-auth these.
        assert self._list_canvases("task:read task:write dashboard:read") == 403
