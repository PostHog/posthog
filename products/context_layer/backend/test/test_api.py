import tempfile
import subprocess
from pathlib import Path

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

import posthog.storage.object_storage as object_storage_module
from posthog.models.scoping import team_scope
from posthog.storage.object_storage import UnavailableStorage

from products.context_layer.backend import store
from products.tasks.backend.facade import api as tasks_facade


@override_settings(OBJECT_STORAGE_ENABLED=True)
@patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
class TestContextLayerAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        object_storage_module._client = UnavailableStorage()
        self.addCleanup(setattr, object_storage_module, "_client", UnavailableStorage())
        self.base_url = f"/api/organizations/{self.organization.id}/context_layer"

    def _enable(self) -> str:
        response = self.client.post(f"{self.base_url}/enable/")
        assert response.status_code == 201, response.content
        return response.json()["head_sha"]

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
        assert "private projects" in response.json()["detail"]

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
            {"path": "areas/analytics.md", "content": "# Analytics\n", "base_head": head},
            format="json",
        )
        assert response.status_code == 200, response.content
        new_head = response.json()["head_sha"]
        assert new_head != head

        page = self.client.get(f"{self.base_url}/pages/", {"path": "areas/analytics.md"}).json()
        assert page["content"] == "# Analytics\n"
        assert page["head_sha"] == new_head

    def test_page_write_with_stale_base_head_returns_409_with_current_head(self, _flag) -> None:
        head = self._enable()
        first = self.client.put(
            f"{self.base_url}/pages/",
            {"path": "areas/replay.md", "content": "# Replay\n", "base_head": head},
            format="json",
        )
        assert first.status_code == 200
        stale = self.client.put(
            f"{self.base_url}/pages/",
            {"path": "areas/replay.md", "content": "# Replay, but stale\n", "base_head": head},
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
        bundle_bytes = self._bundle_with_edit("areas/from-agent.md", "# From an agent\n")
        response = self.client.post(
            f"{self.base_url}/commits/",
            {"bundle": SimpleUploadedFile("out.bundle", bundle_bytes)},
            format="multipart",
        )
        assert response.status_code == 200, response.content
        page = self.client.get(f"{self.base_url}/pages/", {"path": "areas/from-agent.md"}).json()
        assert page["content"] == "# From an agent\n"

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

    def test_export_returns_a_download_url(self, _flag) -> None:
        head = self._enable()
        response = self.client.get(f"{self.base_url}/export/")
        assert response.status_code == 200
        body = response.json()
        assert body["head_sha"] == head
        assert body["url"].startswith("http")

    def _bundle_with_edit(self, path: str, content: str) -> bytes:
        """Clone the wiki the way a sandbox does, commit one edit, pack it as a thin bundle."""
        with store.checkout_repo(self.organization.id) as checkout:
            target = checkout.path / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            env_git = ["git", "-c", "user.name=agent", "-c", "user.email=agent@example.com"]
            subprocess.run([*env_git, "add", "--all"], cwd=checkout.path, check=True)
            subprocess.run([*env_git, "commit", "--quiet", "-m", f"Edit {path}"], cwd=checkout.path, check=True)
            with tempfile.NamedTemporaryFile(suffix=".bundle") as bundle_file:
                subprocess.run(
                    [*env_git, "bundle", "create", bundle_file.name, "origin/main..main"],
                    cwd=checkout.path,
                    check=True,
                )
                return Path(bundle_file.name).read_bytes()
