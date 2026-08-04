from datetime import timedelta
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest

from django.utils import timezone

from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.scoping import team_scope
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

from products.tasks.backend.models import Channel, Task


class TestCanvasOAuthAccess(APIBaseTest):
    """The desktop app reaches /canvases/ exclusively through OAuth bearer tokens,
    a path session-authenticated API tests never exercise. Wildcard covers the
    grandfathered `*` grant; `canvas:read` covers tokens narrowed to an app's
    scope ceiling at grant time (which must include the canvas scope)."""

    def _bearer(self, scope: str, client_id: str | None = None) -> str:
        app = OAuthApplication.objects.create(
            name="desktop",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            skip_authorization=False,
            organization=self.organization,
            user=self.user,
            **({"client_id": client_id} if client_id else {}),
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

    def _list_canvases(self, scope: str, client_id: str | None = None) -> int:
        with team_scope(self.team.id):
            channel = Channel.objects.create(team=self.team, name="general")
        token = self._bearer(scope, client_id=client_id)
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

    def test_list_canvases_with_legacy_desktop_oauth_token(self):
        assert (
            self._list_canvases(
                "task:read task:write dashboard:read",
                client_id=ARRAY_APP_CLIENT_ID_DEV,
            )
            == 200
        )

    def test_list_canvases_denied_without_canvas_scope_for_other_apps(self):
        assert self._list_canvases("task:read task:write dashboard:read") == 403

    def _create_canvas(
        self,
        *,
        client_id: str | None,
        task_header: str | None,
        scope: str = "*",
        expected_status: int = 201,
    ) -> dict:
        with team_scope(self.team.id):
            channel = Channel.objects.create(team=self.team, name="general")
        token = self._bearer(scope, client_id=client_id)
        self.client.logout()
        extra: dict[str, Any] = {"HTTP_X_POSTHOG_TASK_ID": task_header} if task_header else {}
        res = self.client.post(
            f"/api/projects/{self.team.id}/canvases/",
            {"channel_id": str(channel.id), "name": "Signups"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
            **extra,
        )
        assert res.status_code == expected_status, res.json()
        return res.json()

    def test_create_canvas_with_legacy_desktop_oauth_token(self):
        body = self._create_canvas(
            client_id=ARRAY_APP_CLIENT_ID_DEV,
            task_header=None,
            scope="task:write dashboard:write",
        )
        assert body["name"] == "Signups"

    def test_create_canvas_denied_with_legacy_scope_for_other_apps(self):
        self._create_canvas(
            client_id=None,
            task_header=None,
            scope="task:write dashboard:write",
            expected_status=403,
        )

    def test_sandbox_create_binds_the_generating_task(self):
        # Composer-initiated generations have no client-side create, so the
        # sandbox's stamped task header is what records which run produced the
        # canvas — that link powers the task nesting and generating state.
        task = Task.objects.create(team=self.team, created_by=self.user, title="Generate canvas")
        body = self._create_canvas(client_id=ARRAY_APP_CLIENT_ID_DEV, task_header=str(task.id))
        assert body["generation_task_id"] == str(task.id)

    def test_non_sandbox_create_ignores_the_task_header(self):
        # The header alone is forgeable; only sandbox-minted credentials count.
        task = Task.objects.create(team=self.team, created_by=self.user, title="Generate canvas")
        body = self._create_canvas(client_id=None, task_header=str(task.id))
        assert body["generation_task_id"] is None

    def test_sandbox_create_ignores_a_task_outside_the_team(self):
        body = self._create_canvas(client_id=ARRAY_APP_CLIENT_ID_DEV, task_header=str(uuid4()))
        assert body["generation_task_id"] is None
