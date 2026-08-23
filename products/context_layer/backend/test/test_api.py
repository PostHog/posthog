import tempfile
import subprocess
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

import posthog.storage.object_storage as object_storage_module
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.storage.object_storage import UnavailableStorage

from products.context_layer.backend import enablement, store
from products.tasks.backend.facade import api as tasks_facade

from ee.models.rbac.access_control import AccessControl


def _page(title: str) -> str:
    return f"---\nsummary: {title} page for API tests.\nstatus: active\n---\n# {title}\n"


@override_settings(OBJECT_STORAGE_ENABLED=True)
@patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
class TestContextLayerAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        object_storage_module._client = UnavailableStorage()
        self.addCleanup(setattr, object_storage_module, "_client", UnavailableStorage())
        self.base_url = f"/api/organizations/{self.organization.id}/context_layer"
        self.agent_url = f"/api/projects/{self.team.id}/context_layer/agent"

    def _enable(self) -> str:
        response = self.client.post(f"{self.base_url}/enable/")
        assert response.status_code == 201, response.content
        return response.json()["head_sha"]

    def _bearer(self, scope: str, *, scoped_teams: list[int] | None = None, sandbox_task_id=None) -> str:  # noqa: ANN001
        app = OAuthApplication.objects.create(
            name="sandbox",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=app,
            token=f"pha_{uuid4().hex}",
            scope=scope,
            expires=timezone.now() + timedelta(hours=1),
            scoped_teams=scoped_teams or [],
            scoped_organizations=[],
            sandbox_task_id=sandbox_task_id,
        )
        return token.token

    def test_agent_route_accepts_the_run_token_the_org_route_refuses(self, _flag) -> None:
        self._enable()
        bundle_bytes = self._bundle_with_edit("areas/from-agent.md", _page("From an agent"))
        # Minted the way production mints one: bound to a task, scoped to a team.
        token = self._bearer("task:write internal_run:read", scoped_teams=[self.team.id])
        self.client.logout()

        def post(base: str):
            return self.client.post(
                f"{base}/commits/",
                {"bundle": SimpleUploadedFile("out.bundle", bundle_bytes)},
                format="multipart",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )

        assert post(self.agent_url).status_code == 200

        # APIScopePermission refuses any token carrying scoped_teams on a route
        # that is not project-nested, which is the whole reason the agent route
        # exists — without it no real sandbox token can publish at all.
        assert post(self.base_url).status_code == 403

    def test_enable_scaffolds_wiki_and_imports_channel_context(self, _flag) -> None:
        with team_scope(self.team.id):
            channel = tasks_facade.resolve_channel(self.team.id, self.user.id, name="growth", star=False)
            assert channel is not None
            tasks_facade.publish_channel_instructions(
                channel.id, self.team.id, self.user.id, content="Focus on activation.", base_version=0
            )

        self._enable()

        tree = self.client.get(f"{self.base_url}/tree/").json()
        assert "AGENTS.md" in tree["paths"]
        assert "channels/growth.md" in tree["paths"]
        page = self.client.get(f"{self.base_url}/pages/", {"path": "channels/growth.md"}).json()
        assert f"channel_id: {channel.id}" in page["content"]
        assert "Focus on activation." in page["content"]

    def test_enable_is_blocked_for_orgs_with_private_projects(self, _flag) -> None:
        self.team.access_control = True
        self.team.save()
        response = self.client.post(f"{self.base_url}/enable/")
        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "private_projects"
        assert self.team.name in body["detail"]

    def test_enable_is_blocked_for_orgs_with_rbac_private_projects(self, _flag) -> None:
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="none",
        )
        response = self.client.post(f"{self.base_url}/enable/")
        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "private_projects"
        assert self.team.name in body["detail"]

    def test_reimport_keeps_existing_pages_and_suffixes_colliding_new_channels(self, _flag) -> None:
        with team_scope(self.team.id):
            channel = tasks_facade.resolve_channel(self.team.id, self.user.id, name="growth", star=False)
            assert channel is not None
            tasks_facade.publish_channel_instructions(
                channel.id, self.team.id, self.user.id, content="First import.", base_version=0
            )
        self._enable()

        other_team = Team.objects.create(organization=self.organization, name="Second project")
        with team_scope(other_team.id):
            colliding = tasks_facade.resolve_channel(other_team.id, self.user.id, name="growth", star=False)
            assert colliding is not None
            tasks_facade.publish_channel_instructions(
                colliding.id, other_team.id, self.user.id, content="Same name, other project.", base_version=0
            )
        enablement.import_channel_context(self.organization.id)

        tree = self.client.get(f"{self.base_url}/tree/").json()
        suffixed = f"channels/growth-{str(colliding.id)[:8]}.md"
        assert "channels/growth.md" in tree["paths"]
        assert suffixed in tree["paths"]
        original = self.client.get(f"{self.base_url}/pages/", {"path": "channels/growth.md"}).json()
        assert "First import." in original["content"]

    def test_enable_returns_429_when_a_writer_holds_the_lock(self, _flag) -> None:
        with patch(
            "products.context_layer.backend.store.repo_writer_lock",
            side_effect=store.RepoLockUnavailableError("another writer holds the lock"),
        ):
            response = self.client.post(f"{self.base_url}/enable/")
        assert response.status_code == 429

    def test_endpoints_404_before_enablement(self, _flag) -> None:
        assert self.client.get(f"{self.base_url}/tree/").status_code == 404
        assert self.client.get(f"{self.base_url}/status/").status_code == 404

    def test_flag_off_blocks_the_surface(self, flag_mock) -> None:
        flag_mock.return_value = False
        assert self.client.post(f"{self.base_url}/enable/").status_code == 403

    def test_page_write_moves_head_and_read_returns_new_content(self, _flag) -> None:
        head = self._enable()
        response = self.client.put(
            f"{self.base_url}/pages/",
            {"path": "areas/analytics.md", "content": _page("Analytics"), "base_head": head},
            format="json",
        )
        assert response.status_code == 200, response.content
        new_head = response.json()["head_sha"]
        assert new_head != head

        page = self.client.get(f"{self.base_url}/pages/", {"path": "areas/analytics.md"}).json()
        assert page["content"] == _page("Analytics")
        assert page["head_sha"] == new_head

    def test_page_write_with_stale_base_head_returns_409_with_current_head(self, _flag) -> None:
        head = self._enable()
        first = self.client.put(
            f"{self.base_url}/pages/",
            {"path": "areas/replay.md", "content": _page("Replay"), "base_head": head},
            format="json",
        )
        assert first.status_code == 200
        stale = self.client.put(
            f"{self.base_url}/pages/",
            {"path": "areas/replay.md", "content": _page("Replay, but stale"), "base_head": head},
            format="json",
        )
        assert stale.status_code == 409
        assert stale.json()["current_head"] == first.json()["head_sha"]

    def test_page_write_outside_the_structure_returns_400(self, _flag) -> None:
        self._enable()
        response = self.client.put(
            f"{self.base_url}/pages/",
            {"path": "rogue.md", "content": "# rogue\n"},
            format="json",
        )
        assert response.status_code == 400

    def test_page_write_with_traversal_path_returns_400(self, _flag) -> None:
        self._enable()
        response = self.client.put(
            f"{self.base_url}/pages/",
            {"path": "../escape.md", "content": "# escape\n"},
            format="json",
        )
        assert response.status_code == 400

    def test_commits_endpoint_lands_a_bundle(self, _flag) -> None:
        self._enable()
        bundle_bytes = self._bundle_with_edit("areas/from-agent.md", _page("From an agent"))
        response = self.client.post(
            f"{self.base_url}/commits/",
            {"bundle": SimpleUploadedFile("out.bundle", bundle_bytes)},
            format="multipart",
        )
        assert response.status_code == 200, response.content
        page = self.client.get(f"{self.base_url}/pages/", {"path": "areas/from-agent.md"}).json()
        assert page["content"] == _page("From an agent")

    def _post_bundle_with_bearer(self, scope: str):
        # The project-nested agent route, with a token minted the way production
        # mints a run token: scoped to a team. The org route refuses a
        # scoped_teams token outright — see
        # test_agent_route_accepts_the_run_token_the_org_route_refuses.
        self._enable()
        bundle_bytes = self._bundle_with_edit("areas/from-agent.md", _page("From an agent"))
        token = self._bearer(scope, scoped_teams=[self.team.id])
        self.client.logout()
        return self.client.post(
            f"{self.agent_url}/commits/",
            {"bundle": SimpleUploadedFile("out.bundle", bundle_bytes)},
            format="multipart",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def test_commits_accepts_a_sandbox_run_token(self, _flag) -> None:
        assert self._post_bundle_with_bearer("task:write internal_run:read").status_code == 200

    def test_commits_rejects_task_write_without_run_provenance(self, _flag) -> None:
        # task:write is user-grantable; without the server-minted internal_run:read
        # marker the caller must hold organization:write like any other writer.
        assert self._post_bundle_with_bearer("task:write").status_code == 403

    def test_commits_endpoint_rejects_lint_violations(self, _flag) -> None:
        self._enable()
        bundle_bytes = self._bundle_with_edit("rogue.txt", "nope")
        response = self.client.post(
            f"{self.base_url}/commits/",
            {"bundle": SimpleUploadedFile("out.bundle", bundle_bytes)},
            format="multipart",
        )
        assert response.status_code == 400
        assert response.json()["errors"]

    def test_commits_endpoint_rejects_bundles_whose_history_violates_structure(self, _flag) -> None:
        self._enable()
        with store.checkout_repo(self.organization.id) as checkout:
            env_git = ["git", "-c", "user.name=agent", "-c", "user.email=agent@example.com"]
            rogue = checkout.path / "secrets.txt"
            rogue.write_text("hazardous dump")
            subprocess.run([*env_git, "add", "--all"], cwd=checkout.path, check=True)
            subprocess.run([*env_git, "commit", "--quiet", "-m", "Add hazard"], cwd=checkout.path, check=True)
            rogue.unlink()
            (checkout.path / "areas").mkdir(exist_ok=True)
            (checkout.path / "areas" / "clean.md").write_text("# Clean\n")
            subprocess.run([*env_git, "add", "--all"], cwd=checkout.path, check=True)
            subprocess.run([*env_git, "commit", "--quiet", "-m", "Remove hazard"], cwd=checkout.path, check=True)
            with tempfile.NamedTemporaryFile(suffix=".bundle") as bundle_file:
                subprocess.run(
                    [*env_git, "bundle", "create", bundle_file.name, "origin/main..main"],
                    cwd=checkout.path,
                    check=True,
                )
                bundle_bytes = Path(bundle_file.name).read_bytes()

        response = self.client.post(
            f"{self.base_url}/commits/",
            {"bundle": SimpleUploadedFile("out.bundle", bundle_bytes)},
            format="multipart",
        )
        assert response.status_code == 400
        assert any("secrets.txt" in error for error in response.json()["errors"])

    def test_commits_endpoint_rejects_bundles_with_too_many_commits(self, _flag) -> None:
        self._enable()
        with store.checkout_repo(self.organization.id) as checkout:
            env_git = ["git", "-c", "user.name=agent", "-c", "user.email=agent@example.com"]
            (checkout.path / "areas").mkdir(exist_ok=True)
            for index in range(4):
                (checkout.path / "areas" / f"page-{index}.md").write_text(f"# Page {index}\n")
                subprocess.run([*env_git, "add", "--all"], cwd=checkout.path, check=True)
                subprocess.run(
                    [*env_git, "commit", "--quiet", "-m", f"Add page {index}"], cwd=checkout.path, check=True
                )
            with tempfile.NamedTemporaryFile(suffix=".bundle") as bundle_file:
                subprocess.run(
                    [*env_git, "bundle", "create", bundle_file.name, "origin/main..main"],
                    cwd=checkout.path,
                    check=True,
                )
                bundle_bytes = Path(bundle_file.name).read_bytes()

        with patch.object(store, "BUNDLE_MAX_COMMITS", 3):
            response = self.client.post(
                f"{self.base_url}/commits/",
                {"bundle": SimpleUploadedFile("out.bundle", bundle_bytes)},
                format="multipart",
            )
        assert response.status_code == 409
        assert "at most 3" in response.json()["detail"]

    def test_commits_endpoint_lands_a_dream_branch_as_one_merge_commit(self, _flag) -> None:
        self._enable()
        bundle_bytes = self._bundle_with_edit("areas/dreamt.md", "# Dreamt\n", branch="dream/2026-08-18")
        response = self.client.post(
            f"{self.base_url}/commits/",
            {"bundle": SimpleUploadedFile("out.bundle", bundle_bytes), "branch": "dream/2026-08-18"},
            format="multipart",
        )
        assert response.status_code == 200, response.content
        page = self.client.get(f"{self.base_url}/pages/", {"path": "areas/dreamt.md"}).json()
        assert page["content"] == "# Dreamt\n"
        with store.checkout_repo(self.organization.id) as checkout:
            merges = subprocess.run(
                ["git", "log", "--merges", "--format=%s"], cwd=checkout.path, capture_output=True, text=True
            ).stdout
            assert "dream: 2026-08-18" in merges

    def test_commits_endpoint_rejects_non_dream_branches(self, _flag) -> None:
        self._enable()
        bundle_bytes = self._bundle_with_edit("areas/rogue-branch.md", "# Rogue\n", branch="dream/2026-08-18")
        response = self.client.post(
            f"{self.base_url}/commits/",
            {"bundle": SimpleUploadedFile("out.bundle", bundle_bytes), "branch": "feature/anything"},
            format="multipart",
        )
        assert response.status_code == 400

    def test_commits_endpoint_rejects_bundles_with_merge_commits(self, _flag) -> None:
        self._enable()
        with store.checkout_repo(self.organization.id) as checkout:
            env_git = ["git", "-c", "user.name=agent", "-c", "user.email=agent@example.com"]
            subprocess.run([*env_git, "checkout", "--quiet", "-b", "side"], cwd=checkout.path, check=True)
            (checkout.path / "areas").mkdir(exist_ok=True)
            (checkout.path / "areas" / "side.md").write_text("# Side\n")
            subprocess.run([*env_git, "add", "--all"], cwd=checkout.path, check=True)
            subprocess.run([*env_git, "commit", "--quiet", "-m", "Side edit"], cwd=checkout.path, check=True)
            subprocess.run([*env_git, "checkout", "--quiet", "main"], cwd=checkout.path, check=True)
            (checkout.path / "areas").mkdir(exist_ok=True)
            (checkout.path / "areas" / "main.md").write_text("# Main\n")
            subprocess.run([*env_git, "add", "--all"], cwd=checkout.path, check=True)
            subprocess.run([*env_git, "commit", "--quiet", "-m", "Main edit"], cwd=checkout.path, check=True)
            subprocess.run(
                [*env_git, "merge", "--no-ff", "--quiet", "-m", "Merge side", "side"], cwd=checkout.path, check=True
            )
            with tempfile.NamedTemporaryFile(suffix=".bundle") as bundle_file:
                subprocess.run(
                    [*env_git, "bundle", "create", bundle_file.name, "origin/main..main"],
                    cwd=checkout.path,
                    check=True,
                )
                bundle_bytes = Path(bundle_file.name).read_bytes()

        response = self.client.post(
            f"{self.base_url}/commits/",
            {"bundle": SimpleUploadedFile("out.bundle", bundle_bytes)},
            format="multipart",
        )
        assert response.status_code == 409
        assert "merge commits" in response.json()["detail"]

    def test_wiki_goes_dark_when_a_project_becomes_private(self, _flag) -> None:
        self._enable()
        assert self.client.get(f"{self.base_url}/tree/").status_code == 200

        self.team.access_control = True
        self.team.save()

        assert self.client.get(f"{self.base_url}/tree/").status_code == 403
        assert self.client.get(f"{self.base_url}/pages/", {"path": "AGENTS.md"}).status_code == 403
        assert self.client.get(f"{self.base_url}/export/").status_code == 403

    def test_export_returns_a_download_url(self, _flag) -> None:
        head = self._enable()
        response = self.client.get(f"{self.base_url}/export/")
        assert response.status_code == 200
        body = response.json()
        assert body["head_sha"] == head
        assert body["url"].startswith("http")

    def _bundle_with_edit(self, path: str, content: str, branch: str = "main") -> bytes:
        """Clone the wiki the way a sandbox does, commit one edit, pack it as a thin bundle."""
        with store.checkout_repo(self.organization.id) as checkout:
            env_git = ["git", "-c", "user.name=agent", "-c", "user.email=agent@example.com"]
            if branch != "main":
                subprocess.run([*env_git, "checkout", "--quiet", "-b", branch], cwd=checkout.path, check=True)
            target = checkout.path / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            subprocess.run([*env_git, "add", "--all"], cwd=checkout.path, check=True)
            subprocess.run([*env_git, "commit", "--quiet", "-m", f"Edit {path}"], cwd=checkout.path, check=True)
            with tempfile.NamedTemporaryFile(suffix=".bundle") as bundle_file:
                subprocess.run(
                    [*env_git, "bundle", "create", bundle_file.name, f"origin/main..{branch}"],
                    cwd=checkout.path,
                    check=True,
                )
                return Path(bundle_file.name).read_bytes()
