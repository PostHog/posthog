"""API tests for agent_stack."""

from __future__ import annotations

import hashlib

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.agent_stack.backend.enums import DeploymentStatus, RevisionState, SessionState
from products.agent_stack.backend.models import AgentApplication, AgentApplicationRevision, AgentApplicationSession

SHA = hashlib.sha256(b"bundle").hexdigest()


def _presigned_stub(*args, **kwargs):
    return {"url": "https://example-bucket.s3.amazonaws.com/", "fields": {"key": "x", "policy": "y"}}


def _create_app(team, slug="myapp", name="My App") -> AgentApplication:
    return AgentApplication.objects.create(team=team, slug=slug, name=name)


def _create_revision(app, *, state=RevisionState.READY, deployment_status=DeploymentStatus.DISABLED):
    return AgentApplicationRevision.objects.create(
        team=app.team,
        application=app,
        state=state,
        deployment_status=deployment_status,
        bundle_sha256=SHA,
        bundle_size=1024,
        top_level_config={},
    )


class TestAgentApplicationCRUD(APIBaseTest):
    def _url(self, *segments) -> str:
        return f"/api/projects/{self.team.id}/agent_applications/" + "".join(segments)

    def test_list_empty(self):
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    def test_create_application(self):
        response = self.client.post(
            self._url(),
            data={"name": "My App", "slug": "myapp", "description": "hello"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["slug"] == "myapp"
        assert body["name"] == "My App"
        assert body["has_env"] is False
        assert AgentApplication.objects.filter(slug="myapp", team=self.team).exists()

    def test_create_rejects_invalid_slug(self):
        response = self.client.post(
            self._url(),
            data={"name": "X", "slug": "-bad-start"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_rejects_duplicate_active_slug(self):
        _create_app(self.team, slug="taken")
        response = self.client.post(
            self._url(),
            data={"name": "Other", "slug": "taken"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "slug"

    def test_retrieve_by_uuid_and_by_slug(self):
        app = _create_app(self.team, slug="dual")
        for lookup in (str(app.id), "dual"):
            response = self.client.get(self._url(f"{lookup}/"))
            assert response.status_code == status.HTTP_200_OK, lookup
            assert response.json()["slug"] == "dual"

    def test_retrieve_404(self):
        response = self.client.get(self._url("nope/"))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_partial_update(self):
        app = _create_app(self.team)
        response = self.client.patch(
            self._url(f"{app.slug}/"),
            data={"description": "updated"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["description"] == "updated"

    def test_destroy_is_soft_delete(self):
        app = _create_app(self.team)
        response = self.client.delete(self._url(f"{app.id}/"))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        app.refresh_from_db()
        assert app.deleted is True
        assert app.deleted_at is not None
        # List no longer surfaces it.
        assert self.client.get(self._url()).json()["results"] == []

    def test_team_scoping(self):
        from posthog.models import Organization, Team

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        _create_app(other_team, slug="other-team-app")
        _create_app(self.team, slug="my-team-app")

        response = self.client.get(self._url())
        slugs = {r["slug"] for r in response.json()["results"]}
        assert slugs == {"my-team-app"}


class TestStartDeploy(APIBaseTest):
    def _url(self, app) -> str:
        return f"/api/projects/{self.team.id}/agent_applications/{app.slug}/start_deploy/"

    @patch(
        "products.agent_stack.backend.deploys.object_storage.object_storage_client",
    )
    def test_happy_path_creates_pending_revision(self, mock_client):
        mock_client.return_value.get_presigned_post.side_effect = _presigned_stub
        app = _create_app(self.team)

        response = self.client.post(
            self._url(app),
            data={"bundle_sha256": SHA, "bundle_size": 1024, "top_level_config": {"foo": "bar"}},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["required_sha256"] == SHA
        assert body["max_size"] == 1024
        assert "upload_url" in body and "upload_fields" in body

        rev = AgentApplicationRevision.objects.get(pk=body["revision_id"])
        assert rev.application_id == app.id
        assert rev.state == RevisionState.PENDING_UPLOAD
        assert rev.bundle_s3_key.startswith(f"agent-bundles/{app.id}/")

    @patch(
        "products.agent_stack.backend.deploys.object_storage.object_storage_client",
    )
    def test_validation_errors(self, mock_client):
        mock_client.return_value.get_presigned_post.side_effect = _presigned_stub
        app = _create_app(self.team)

        # bad sha256
        response = self.client.post(
            self._url(app),
            data={"bundle_sha256": "short", "bundle_size": 1024, "top_level_config": {}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        # zero size
        response = self.client.post(
            self._url(app),
            data={"bundle_sha256": SHA, "bundle_size": 0, "top_level_config": {}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch(
        "products.agent_stack.backend.deploys.object_storage.object_storage_client",
    )
    def test_storage_unavailable(self, mock_client):
        mock_client.return_value.get_presigned_post.return_value = None
        app = _create_app(self.team)
        response = self.client.post(
            self._url(app),
            data={"bundle_sha256": SHA, "bundle_size": 1024, "top_level_config": {}},
            format="json",
        )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


class TestCompleteUpload(APIBaseTest):
    def _url(self, app) -> str:
        return f"/api/projects/{self.team.id}/agent_applications/{app.id}/complete_upload/"

    def test_happy_path(self):
        app = _create_app(self.team)
        rev = _create_revision(app, state=RevisionState.PENDING_UPLOAD)

        response = self.client.post(self._url(app), data={"revision_id": str(rev.id)}, format="json")
        assert response.status_code == status.HTTP_200_OK
        rev.refresh_from_db()
        assert rev.state == RevisionState.READY

    def test_wrong_state_returns_409(self):
        app = _create_app(self.team)
        rev = _create_revision(app, state=RevisionState.FAILED)
        response = self.client.post(self._url(app), data={"revision_id": str(rev.id)}, format="json")
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_revision_for_other_app_returns_404(self):
        app = _create_app(self.team, slug="a")
        other = _create_app(self.team, slug="b")
        rev = _create_revision(other, state=RevisionState.PENDING_UPLOAD)

        response = self.client.post(self._url(app), data={"revision_id": str(rev.id)}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestPromote(APIBaseTest):
    def _url(self, app) -> str:
        return f"/api/projects/{self.team.id}/agent_applications/{app.id}/promote/"

    def test_promote_sets_live_and_demotes_old(self):
        app = _create_app(self.team)
        old_live = _create_revision(app, deployment_status=DeploymentStatus.LIVE)
        new = _create_revision(app)

        response = self.client.post(self._url(app), data={"revision_id": str(new.id)}, format="json")
        assert response.status_code == status.HTTP_200_OK

        new.refresh_from_db()
        old_live.refresh_from_db()
        assert new.deployment_status == DeploymentStatus.LIVE
        assert old_live.deployment_status == DeploymentStatus.DISABLED

    def test_promote_requires_ready(self):
        app = _create_app(self.team)
        rev = _create_revision(app, state=RevisionState.UPLOADED)
        response = self.client.post(self._url(app), data={"revision_id": str(rev.id)}, format="json")
        assert response.status_code == status.HTTP_409_CONFLICT


class TestPreviewAndDisable(APIBaseTest):
    def _url(self, app, action) -> str:
        return f"/api/projects/{self.team.id}/agent_applications/{app.id}/{action}/"

    def test_preview_does_not_demote_live(self):
        app = _create_app(self.team)
        live = _create_revision(app, deployment_status=DeploymentStatus.LIVE)
        target = _create_revision(app)

        response = self.client.post(self._url(app, "preview"), data={"revision_id": str(target.id)}, format="json")
        assert response.status_code == status.HTTP_200_OK

        target.refresh_from_db()
        live.refresh_from_db()
        assert target.deployment_status == DeploymentStatus.PREVIEW
        assert live.deployment_status == DeploymentStatus.LIVE

    def test_preview_requires_ready(self):
        app = _create_app(self.team)
        rev = _create_revision(app, state=RevisionState.PENDING_UPLOAD)
        response = self.client.post(self._url(app, "preview"), data={"revision_id": str(rev.id)}, format="json")
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_disable_works_from_any_state(self):
        app = _create_app(self.team)
        rev = _create_revision(app, state=RevisionState.FAILED, deployment_status=DeploymentStatus.PREVIEW)
        response = self.client.post(
            self._url(app, "disable_revision"),
            data={"revision_id": str(rev.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        rev.refresh_from_db()
        assert rev.deployment_status == DeploymentStatus.DISABLED


class TestUpdateEnv(APIBaseTest):
    def _url(self, app) -> str:
        return f"/api/projects/{self.team.id}/agent_applications/{app.id}/env/"

    def test_env_is_write_only(self):
        app = _create_app(self.team)
        plaintext = "SECRET_KEY=hunter2\nOTHER=abc"

        response = self.client.put(self._url(app), data={"env": plaintext}, format="json")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert "encrypted_env" not in body
        assert "env" not in body
        assert body["has_env"] is True
        # Keys are surfaced as a .env-formatted string, values are redacted.
        assert body["env_redacted"] == "SECRET_KEY=********\nOTHER=********"

        # Plaintext value does not appear in any read endpoint.
        get_response = self.client.get(f"/api/projects/{self.team.id}/agent_applications/{app.id}/")
        assert "hunter2" not in get_response.content.decode()
        assert "abc" not in get_response.content.decode()

        # But it IS stored (decrypts back).
        app.refresh_from_db()
        assert app.encrypted_env == plaintext

    def test_env_redacted_skips_comments_and_blank_lines(self):
        app = _create_app(self.team)
        app.encrypted_env = "# a comment\n\nA=1\n  # indented comment\nB=2\nNO_EQUALS_LINE\n"
        app.save(update_fields=["encrypted_env"])

        response = self.client.get(f"/api/projects/{self.team.id}/agent_applications/{app.id}/")
        assert response.json()["env_redacted"] == "A=********\nB=********"

    def test_env_rejects_invalid_lines(self):
        app = _create_app(self.team)
        # `123BAD=x` has a key starting with a digit, `no-equals` has no `=`.
        bad = "123BAD=oops\nno-equals\nGOOD=ok\n"

        response = self.client.put(self._url(app), data={"env": bad}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["attr"] == "env"
        # The error string surfaces line numbers so the UI can highlight bad rows.
        assert "Line 1" in body["detail"]

    def test_env_rejects_duplicate_keys(self):
        app = _create_app(self.team)
        response = self.client.put(
            self._url(app),
            data={"env": "A=1\nA=2\n"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "duplicate" in response.json()["detail"].lower()

    def test_env_accepts_comments_blanks_and_export(self):
        app = _create_app(self.team)
        good = "# leading comment\n\nexport ANTHROPIC_API_KEY=sk-test\nSLACK_BOT_TOKEN=xoxb\n"
        response = self.client.put(self._url(app), data={"env": good}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["env_redacted"] == "ANTHROPIC_API_KEY=********\nSLACK_BOT_TOKEN=********"

    def test_env_can_be_cleared_with_empty_string(self):
        app = _create_app(self.team)
        app.encrypted_env = "OLD=value"
        app.save(update_fields=["encrypted_env"])

        response = self.client.put(self._url(app), data={"env": ""}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["has_env"] is False
        app.refresh_from_db()
        # Cleared value reads back as None (encrypted mixin writes falsy → null).
        assert not app.encrypted_env


class TestNestedRevisions(APIBaseTest):
    def _url(self, app, *segments) -> str:
        return f"/api/projects/{self.team.id}/agent_applications/{app.slug}/revisions/" + "".join(segments)

    def test_list_scoped_to_parent_app(self):
        app = _create_app(self.team, slug="a")
        other = _create_app(self.team, slug="b")
        _create_revision(app)
        _create_revision(app)
        _create_revision(other)

        response = self.client.get(self._url(app))
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 2
        assert {r["application"] for r in results} == {str(app.id)}

    def test_list_accepts_uuid_or_slug_for_parent(self):
        app = _create_app(self.team)
        _create_revision(app)

        for parent in (str(app.id), app.slug):
            url = f"/api/projects/{self.team.id}/agent_applications/{parent}/revisions/"
            response = self.client.get(url)
            assert response.status_code == status.HTTP_200_OK, parent
            assert len(response.json()["results"]) == 1

    def test_filter_by_deployment_status(self):
        app = _create_app(self.team)
        _create_revision(app, deployment_status=DeploymentStatus.LIVE)
        _create_revision(app, deployment_status=DeploymentStatus.DISABLED)

        response = self.client.get(self._url(app) + "?deployment_status=live")
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["deployment_status"] == DeploymentStatus.LIVE


class TestNestedSessions(APIBaseTest):
    def _url(self, app) -> str:
        return f"/api/projects/{self.team.id}/agent_applications/{app.id}/sessions/"

    def _create_session(self, app, revision, **kwargs) -> AgentApplicationSession:
        return AgentApplicationSession.objects.create(
            team=app.team,
            application=app,
            revision=revision,
            state=kwargs.get("state", SessionState.RUNNING),
            input=kwargs.get("input", {}),
        )

    def test_list_scoped_to_parent_app(self):
        app = _create_app(self.team, slug="a")
        other = _create_app(self.team, slug="b")
        rev_a = _create_revision(app)
        rev_b = _create_revision(other)
        self._create_session(app, rev_a)
        self._create_session(other, rev_b)

        response = self.client.get(self._url(app))
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["application"] == str(app.id)

    def test_filter_by_state(self):
        app = _create_app(self.team)
        rev = _create_revision(app)
        self._create_session(app, rev, state=SessionState.RUNNING)
        self._create_session(app, rev, state=SessionState.COMPLETED)

        response = self.client.get(self._url(app) + "?state=running")
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["state"] == SessionState.RUNNING

    def test_filter_by_created_after(self):
        app = _create_app(self.team)
        rev = _create_revision(app)
        older = self._create_session(app, rev)
        newer = self._create_session(app, rev)

        cutoff = older.created_at.isoformat().replace("+00:00", "Z")
        response = self.client.get(self._url(app) + f"?created_after={cutoff}")
        # gte cutoff includes the older row too — verify cutoff > older returns only newer.
        bumped_cutoff = newer.created_at.isoformat().replace("+00:00", "Z")
        response = self.client.get(self._url(app) + f"?created_after={bumped_cutoff}")
        ids = {r["id"] for r in response.json()["results"]}
        assert ids == {str(newer.id)}
