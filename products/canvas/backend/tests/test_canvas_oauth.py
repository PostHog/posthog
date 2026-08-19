from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from posthog.test.base import APIBaseTest

from django.utils import timezone

from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.scoping import team_scope
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

from products.canvas.backend.models import Canvas
from products.tasks.backend.models import Channel, Task


class TestCanvasOAuthAccess(APIBaseTest):
    """The desktop app reaches /canvases/ exclusively through OAuth bearer tokens,
    a path session-authenticated API tests never exercise. Wildcard covers the
    grandfathered `*` grant; `canvas:read` covers tokens narrowed to an app's
    scope ceiling at grant time (which must include the canvas scope)."""

    def _bearer(self, scope: str, client_id: str | None = None, sandbox_task_id: UUID | None = None) -> str:
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
            sandbox_task_id=sandbox_task_id,
        )
        return token.token

    def _list_canvases(self, scope: str, client_id: str | None = None):
        with team_scope(self.team.id):
            channel = Channel.objects.create(team=self.team, name="general")
            Canvas.objects.create(team=self.team, channel=channel, name="Signups", created_by=self.user)
        token = self._bearer(scope, client_id=client_id)
        self.client.logout()
        return self.client.get(
            f"/api/projects/{self.team.id}/canvases/?channel={channel.id}&limit=200",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def test_list_canvases_with_wildcard_oauth_token(self):
        assert self._list_canvases("*").status_code == 200

    def test_list_canvases_with_canvas_read_oauth_token(self):
        assert self._list_canvases("canvas:read").status_code == 200

    def test_list_canvases_denied_without_canvas_scope(self):
        # A token whose enumerated grant predates the canvas scope: other scopes
        # present, canvas absent. This is what a stale desktop session narrowed
        # to an app's scope ceiling looks like; the client's OAUTH_SCOPE_VERSION
        # bump exists to re-auth these.
        assert self._list_canvases("task:read task:write dashboard:read").status_code == 403

    def test_list_canvases_with_an_interactive_desktop_grant(self):
        # The desktop app's own grants come from the same OAuth apps that mint
        # sandbox tokens, so treating a client-id match as sandbox origin empties
        # every canvas list in the app: no bound task means nothing to scope to.
        response = self._list_canvases("*", client_id=ARRAY_APP_CLIENT_ID_DEV)

        assert response.status_code == 200
        assert [row["name"] for row in response.json()["results"]] == ["Signups"]

    def test_list_canvases_with_an_unbound_server_minted_sandbox_token(self):
        response = self._list_canvases(
            "canvas:read internal_run:read",
            client_id=ARRAY_APP_CLIENT_ID_DEV,
        )

        assert response.status_code == 200
        assert response.json()["results"] == []

    def _create_canvas(
        self,
        *,
        client_id: str | None,
        task_header: str | None,
        sandbox_task: Task | None = None,
    ) -> dict:
        with team_scope(self.team.id):
            channel = Channel.objects.create(team=self.team, name="general")
        if sandbox_task is not None:
            sandbox_task.channel = channel
            sandbox_task.save(update_fields=["channel"])
        token = self._bearer(
            "*",
            client_id=client_id,
            sandbox_task_id=sandbox_task.id if sandbox_task is not None else None,
        )
        self.client.logout()
        extra: dict[str, Any] = {"HTTP_X_POSTHOG_TASK_ID": task_header} if task_header else {}
        res = self.client.post(
            f"/api/projects/{self.team.id}/canvases/",
            {"channel_id": str(channel.id), "name": "Signups"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
            **extra,
        )
        assert res.status_code == 201, res.json()
        return res.json()

    def test_sandbox_create_binds_the_generating_task(self):
        # Composer-initiated generations have no client-side create, so the
        # sandbox's stamped task header is what records which run produced the
        # canvas — that link powers the task nesting and generating state.
        task = Task.objects.create(team=self.team, created_by=self.user, title="Generate canvas")
        body = self._create_canvas(
            client_id=ARRAY_APP_CLIENT_ID_DEV,
            task_header=str(task.id),
            sandbox_task=task,
        )
        assert body["generation_task_id"] == str(task.id)

    def test_non_sandbox_create_ignores_the_task_header(self):
        # The header alone is forgeable; only sandbox-minted credentials count.
        task = Task.objects.create(team=self.team, created_by=self.user, title="Generate canvas")
        body = self._create_canvas(client_id=None, task_header=str(task.id))
        assert body["generation_task_id"] is None

    def test_sandbox_create_rejects_a_task_outside_the_team(self):
        with team_scope(self.team.id):
            channel = Channel.objects.create(team=self.team, name="general")
        token = self._bearer("*", client_id=ARRAY_APP_CLIENT_ID_DEV, sandbox_task_id=uuid4())
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.id}/canvases/",
            {"channel_id": str(channel.id), "name": "Signups"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_POSTHOG_TASK_ID=str(uuid4()),
        )

        assert response.status_code == 403
