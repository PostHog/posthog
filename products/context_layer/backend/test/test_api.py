import tempfile
import subprocess
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.apps import apps
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

import posthog.storage.object_storage as object_storage_module
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.storage.object_storage import UnavailableStorage

from products.access_control.backend.models.access_control import AccessControl
from products.context_layer.backend import enablement, store
from products.context_layer.backend.presentation import views
from products.tasks.backend.facade import api as tasks_facade


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

    def test_enable_returns_the_head_the_import_landed(self, _flag) -> None:
        # Callers pass this straight back as `base_head`, so a sha from before
        # the channel import costs them a conflict on their first write.
        with team_scope(self.team.id):
            channel = tasks_facade.resolve_channel(self.team.id, self.user.id, name="growth", star=False)
            assert channel is not None
            tasks_facade.publish_channel_instructions(
                channel.id, self.team.id, self.user.id, content="Focus on activation.", base_version=0
            )

        head = self._enable()

        assert self.client.get(f"{self.base_url}/status/").json()["head_sha"] == head

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
        path = f"projects/{self.team.id}/spaces/growth.md"
        assert path in tree["paths"]
        assert f"projects/{self.team.id}/index.md" in tree["paths"]
        assert f"projects/{self.team.id}/spaces/index.md" in tree["paths"]
        page = self.client.get(f"{self.base_url}/pages/", {"path": path}).json()
        assert page["updated_at"]
        assert f"team_id: {self.team.id}" in page["content"]
        assert f"channel_id: {channel.id}" in page["content"]
        assert "Focus on activation." in page["content"]

        resolved = self.client.get(f"{self.base_url}/channel-pages/{channel.id}/")
        assert resolved.status_code == 200
        assert resolved.json() == {"path": path, "exists": True}

    def test_enable_sanitizes_malformed_wikilinks_in_legacy_context(self, _flag) -> None:
        with team_scope(self.team.id):
            channel = tasks_facade.resolve_channel(self.team.id, self.user.id, name="research", star=False)
            assert channel is not None
            tasks_facade.publish_channel_instructions(
                channel.id,
                self.team.id,
                self.user.id,
                content="Keep [[areas/insights]] current. Ignore [[../secrets]] and review [[unfinished notes.",
                base_version=0,
            )

        self._enable()

        path = f"projects/{self.team.id}/spaces/research.md"
        page = self.client.get(f"{self.base_url}/pages/", {"path": path}).json()
        assert "[[areas/insights]]" in page["content"]
        assert "&#91;&#91;../secrets&#93;&#93;" in page["content"]
        assert "&#91;&#91;unfinished notes." in page["content"]
        assert "Some wiki-link brackets in this imported context were encoded" in page["content"]

    def test_enable_scaffolds_space_page_without_legacy_context(self, _flag) -> None:
        with team_scope(self.team.id):
            channel = tasks_facade.resolve_channel(self.team.id, self.user.id, name="empty-space", star=False)
            assert channel is not None

        self._enable()

        path = f"projects/{self.team.id}/spaces/empty-space.md"
        tree = self.client.get(f"{self.base_url}/tree/").json()
        assert path in tree["paths"]
        page = self.client.get(f"{self.base_url}/pages/", {"path": path}).json()
        assert f"channel_id: {channel.id}" in page["content"]
        assert "sources: channel-catalog" in page["content"]
        spaces_index = self.client.get(
            f"{self.base_url}/pages/", {"path": f"projects/{self.team.id}/spaces/index.md"}
        ).json()
        assert f"[[projects/{self.team.id}/spaces/empty-space]]" in spaces_index["content"]

    def test_channel_page_resolution_uses_frontmatter_identity(self, _flag) -> None:
        with team_scope(self.team.id):
            channel = tasks_facade.resolve_channel(self.team.id, self.user.id, name="growth", star=False)
            assert channel is not None
            tasks_facade.publish_channel_instructions(
                channel.id, self.team.id, self.user.id, content="First import.", base_version=0
            )
        head = self._enable()

        def rename_page(root: Path) -> None:
            source = root / f"projects/{self.team.id}/spaces/growth.md"
            source.rename(source.with_name("renamed.md"))

        store.apply_changes(self.organization.id, message="Rename channel page", mutate=rename_page, required_head=head)

        resolved = self.client.get(f"{self.base_url}/channel-pages/{channel.id}/")
        assert resolved.status_code == 200
        assert resolved.json() == {"path": f"projects/{self.team.id}/spaces/renamed.md", "exists": True}

    def test_channel_page_resolution_404s_when_channel_has_no_page(self, _flag) -> None:
        self._enable()
        response = self.client.get(f"{self.base_url}/channel-pages/{uuid4()}/")
        assert response.status_code == 404

    @parameterized.expand(["legacy flag", "rbac deny row"])
    def test_a_private_project_does_not_block_the_wiki(self, representation, _flag) -> None:
        # Both representations of a private project used to refuse enablement
        # outright, which locked out every organization that had restricted one.
        if representation == "legacy flag":
            self.team.access_control = True
            self.team.save()
        else:
            AccessControl.objects.create(
                team=self.team,
                resource="project",
                resource_id=str(self.team.id),
                access_level="none",
            )

        self._enable()

        assert self.client.get(f"{self.base_url}/tree/").status_code == 200

    def test_same_named_spaces_are_scoped_to_their_projects(self, _flag) -> None:
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
        original_path = f"projects/{self.team.id}/spaces/growth.md"
        colliding_path = f"projects/{other_team.id}/spaces/growth.md"
        assert original_path in tree["paths"]
        assert colliding_path in tree["paths"]
        assert f"projects/{self.team.id}/index.md" in tree["paths"]
        assert f"projects/{other_team.id}/index.md" in tree["paths"]
        project_index = self.client.get(f"{self.base_url}/pages/", {"path": "projects/index.md"}).json()
        assert f"project_id: {self.team.id}" in project_index["content"]
        assert f"project_id: {other_team.id}" in project_index["content"]
        original_spaces_index = self.client.get(
            f"{self.base_url}/pages/", {"path": f"projects/{self.team.id}/spaces/index.md"}
        ).json()
        colliding_spaces_index = self.client.get(
            f"{self.base_url}/pages/", {"path": f"projects/{other_team.id}/spaces/index.md"}
        ).json()
        assert str(channel.id) in original_spaces_index["content"]
        assert str(colliding.id) in colliding_spaces_index["content"]
        original = self.client.get(f"{self.base_url}/pages/", {"path": original_path}).json()
        assert "First import." in original["content"]
        colliding_page = self.client.get(f"{self.base_url}/pages/", {"path": colliding_path}).json()
        assert "Same name, other project." in colliding_page["content"]

    def test_enable_returns_429_when_a_writer_holds_the_lock(self, _flag) -> None:
        with patch(
            "products.context_layer.backend.store.repo_writer_lock",
            side_effect=store.RepoLockUnavailableError("another writer holds the lock"),
        ):
            response = self.client.post(f"{self.base_url}/enable/")
        assert response.status_code == 429

    def test_enable_returns_503_when_git_binary_is_missing(self, _flag) -> None:
        # A host without git makes every store write shell out to a missing
        # binary. The endpoint must map that to a clean 503, not an unhandled 500.
        with patch.object(
            store.subprocess, "run", side_effect=FileNotFoundError(2, "No such file or directory", "git")
        ):
            response = self.client.post(f"{self.base_url}/enable/")
        assert response.status_code == 503, response.content

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

    def _loop_run_token(self, channel_id) -> str:  # noqa: ANN001
        """A token shaped like the one a context-maintaining loop run carries."""
        task = apps.get_model("tasks", "Task").objects.create(
            team=self.team,
            created_by=self.user,
            title="Keep the space context current",
            origin_product="loop",
        )
        apps.get_model("tasks", "TaskRun").objects.create(
            task=task,
            team=self.team,
            state={
                "config_snapshot": {
                    "context_target": {
                        "channel_id": str(channel_id),
                        "outputs": {"update_context": True},
                    }
                }
            },
        )
        return self._bearer(
            "task:read task:write loop_context_internal:write",
            scoped_teams=[self.team.id],
            sandbox_task_id=task.id,
        )

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

    def test_pages_accept_a_sandbox_run_token(self, _flag) -> None:
        # Reads stay open across the wiki: it is organization-wide reference
        # material every agent is meant to draw on.
        self._enable()
        token = self._bearer("task:read task:write loop_context_internal:write", scoped_teams=[self.team.id])
        self.client.logout()
        page = self.client.get(
            f"{self.agent_url}/pages/",
            {"path": "AGENTS.md"},
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert page.status_code == 200, page.content

    def test_loop_token_writes_only_the_page_configured_for_its_run(self, _flag) -> None:
        with team_scope(self.team.id):
            channel = tasks_facade.resolve_channel(self.team.id, self.user.id, name="growth", star=False)
            assert channel is not None
            tasks_facade.publish_channel_instructions(
                channel.id, self.team.id, self.user.id, content="Focus on activation.", base_version=0
            )
        head = self._enable()
        token = self._loop_run_token(channel.id)
        self.client.logout()

        in_scope = self.client.put(
            f"{self.agent_url}/pages/",
            {
                "path": f"projects/{self.team.id}/spaces/growth.md",
                # A real loop reads the page and edits in place, so the frontmatter
                # that identifies the channel survives the write.
                "content": f"---\nteam_id: {self.team.id}\nchannel_id: {channel.id}\nsummary: Growth channel context.\nstatus: active\n---\n\n# Growth (project {self.team.id})\n\nRefreshed by the loop.\n",
                "base_head": head,
            },
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert in_scope.status_code == 200, in_scope.content

        # AGENTS.md is what every agent bootstraps from, so a loop reaching it
        # would rewrite the whole organization's starting instructions.
        out_of_scope = self.client.put(
            f"{self.agent_url}/pages/",
            {"path": "AGENTS.md", "content": "# Owned\n", "base_head": in_scope.json()["head_sha"]},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert out_of_scope.status_code == 403, out_of_scope.content

    def test_agent_channel_page_proposes_a_create_path_when_channel_has_no_page(self, _flag) -> None:
        self._enable()
        with team_scope(self.team.id):
            channel = tasks_facade.resolve_channel(self.team.id, self.user.id, name="growth", star=False)
            assert channel is not None

        # The org route keeps its 404 — the desktop hook relies on it.
        assert self.client.get(f"{self.base_url}/channel-pages/{channel.id}/").status_code == 404

        token = self._loop_run_token(channel.id)
        self.client.logout()
        proposed = self.client.get(
            f"{self.agent_url}/channel-pages/{channel.id}/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert proposed.status_code == 200, proposed.content
        assert proposed.json() == {"path": f"projects/{self.team.id}/spaces/growth.md", "exists": False}

    def test_loop_token_creates_its_channels_missing_page_at_the_proposed_path(self, _flag) -> None:
        self._enable()
        with team_scope(self.team.id):
            channel = tasks_facade.resolve_channel(self.team.id, self.user.id, name="growth", star=False)
            assert channel is not None
        token = self._loop_run_token(channel.id)
        self.client.logout()

        created = self.client.put(
            f"{self.agent_url}/pages/",
            {
                "path": f"projects/{self.team.id}/spaces/growth.md",
                "content": f"---\nteam_id: {self.team.id}\nchannel_id: {channel.id}\nsummary: Growth channel context.\nstatus: active\n---\n\n# Growth (project {self.team.id})\n\nWritten by the loop.\n",
            },
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert created.status_code == 200, created.content

        resolved = self.client.get(
            f"{self.agent_url}/channel-pages/{channel.id}/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert resolved.json() == {"path": f"projects/{self.team.id}/spaces/growth.md", "exists": True}

    @parameterized.expand(
        [
            ("mismatched_frontmatter_channel", "projects/{team_id}/spaces/growth.md", False),
            ("non_proposed_path", "projects/{team_id}/spaces/somewhere-else.md", True),
        ]
    )
    def test_loop_token_cannot_create_a_channel_page_off_its_proposal(
        self, _flag, _name, path, own_frontmatter
    ) -> None:
        self._enable()
        with team_scope(self.team.id):
            channel = tasks_facade.resolve_channel(self.team.id, self.user.id, name="growth", star=False)
            assert channel is not None
        token = self._loop_run_token(channel.id)
        self.client.logout()

        frontmatter_channel_id = channel.id if own_frontmatter else uuid4()
        response = self.client.put(
            f"{self.agent_url}/pages/",
            {
                "path": path.format(team_id=self.team.id),
                "content": f"---\nteam_id: {self.team.id}\nchannel_id: {frontmatter_channel_id}\nsummary: Growth channel context.\nstatus: active\n---\n\n# Growth (project {self.team.id})\n",
            },
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 403, response.content

    def test_run_commit_landings_are_capped_per_day(self, _flag) -> None:
        self._enable()
        task = apps.get_model("tasks", "Task").objects.create(team=self.team, created_by=self.user, title="agent work")
        token = self._bearer("task:write internal_run:read", scoped_teams=[self.team.id], sandbox_task_id=task.id)
        self.client.logout()

        def land(path: str):
            bundle_bytes = self._bundle_with_edit(path, _page(path))
            return self.client.post(
                f"{self.agent_url}/commits/",
                {"bundle": SimpleUploadedFile("out.bundle", bundle_bytes)},
                format="multipart",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )

        with patch.object(views, "RUN_COMMITS_PER_DAY_CAP", 1):
            assert land("areas/first.md").status_code == 200
            capped = land("areas/second.md")
        assert capped.status_code == 429

    def test_loop_token_cannot_land_commit_bundles(self, _flag) -> None:
        # Bundles bypass the loop's page binding, so the bundle route must refuse them.
        self._enable()
        with team_scope(self.team.id):
            channel = tasks_facade.resolve_channel(self.team.id, self.user.id, name="growth", star=False)
            assert channel is not None
        bundle_bytes = self._bundle_with_edit("areas/from-agent.md", _page("From an agent"))
        token = self._loop_run_token(channel.id)
        self.client.logout()
        response = self.client.post(
            f"{self.agent_url}/commits/",
            {"bundle": SimpleUploadedFile("out.bundle", bundle_bytes)},
            format="multipart",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 403, response.content

    def test_run_page_writes_share_the_daily_landing_cap(self, _flag) -> None:
        head = self._enable()
        task = apps.get_model("tasks", "Task").objects.create(team=self.team, created_by=self.user, title="agent work")
        token = self._bearer(
            "task:read task:write internal_run:read organization:write",
            scoped_teams=[self.team.id],
            sandbox_task_id=task.id,
        )
        self.client.logout()

        def write(path: str, base_head: str):
            return self.client.put(
                f"{self.agent_url}/pages/",
                {"path": path, "content": _page(path), "base_head": base_head},
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )

        with patch.object(views, "RUN_COMMITS_PER_DAY_CAP", 1):
            first = write("areas/first.md", head)
            assert first.status_code == 200, first.content
            capped = write("areas/second.md", first.json()["head_sha"])
        assert capped.status_code == 429

    def test_pages_reject_task_scopes_without_run_provenance(self, _flag) -> None:
        self._enable()
        token = self._bearer("task:read task:write internal_run:read", scoped_teams=[self.team.id])
        self.client.logout()
        response = self.client.get(
            f"{self.agent_url}/pages/",
            {"path": "areas/analytics.md"},
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 403

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
        bundle_bytes = self._bundle_with_edit("areas/dreamt.md", _page("Dreamt"), branch="dream/2026-08-18")
        response = self.client.post(
            f"{self.base_url}/commits/",
            {"bundle": SimpleUploadedFile("out.bundle", bundle_bytes), "branch": "dream/2026-08-18"},
            format="multipart",
        )
        assert response.status_code == 200, response.content
        page = self.client.get(f"{self.base_url}/pages/", {"path": "areas/dreamt.md"}).json()
        assert page["content"] == _page("Dreamt")
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
