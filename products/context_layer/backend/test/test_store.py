from pathlib import Path

from posthog.test.base import BaseTest

from django.test import override_settings

import posthog.storage.object_storage as object_storage_module
from posthog.storage.object_storage import UnavailableStorage

from products.context_layer.backend import store
from products.context_layer.backend.models import ContextLayerConfig


@override_settings(OBJECT_STORAGE_ENABLED=True)
class TestContextLayerStore(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # The module-level client is cached from whichever settings were active
        # first; reset it so this class always runs against real object storage.
        object_storage_module._client = UnavailableStorage()
        self.addCleanup(setattr, object_storage_module, "_client", UnavailableStorage())

    def test_initialize_repo_scaffolds_default_structure(self) -> None:
        config = store.initialize_repo(self.organization.id, created_by_id=self.user.id)

        assert len(config.head_sha) == 40
        with store.checkout_repo(self.organization.id) as checkout:
            assert checkout.head_sha == config.head_sha
            assert (checkout.path / "AGENTS.md").is_file()
            assert (checkout.path / "CLAUDE.md").is_symlink()
            assert (checkout.path / "org" / "overview.md").is_file()
            assert (checkout.path / "scripts" / "lint").is_file()

    def test_initialize_repo_is_idempotent(self) -> None:
        first = store.initialize_repo(self.organization.id)
        second = store.initialize_repo(self.organization.id)
        assert first.id == second.id
        assert first.head_sha == second.head_sha

    def test_apply_changes_lands_commit_and_moves_head(self) -> None:
        config = store.initialize_repo(self.organization.id)

        def add_area_page(root: Path) -> None:
            (root / "areas").mkdir(exist_ok=True)
            (root / "areas" / "analytics.md").write_text("# Analytics\n\nCurrent state and direction.\n")

        new_head = store.apply_changes(
            self.organization.id, message="Add the analytics area page", mutate=add_area_page
        )

        assert new_head != config.head_sha
        config.refresh_from_db()
        assert config.head_sha == new_head
        with store.checkout_repo(self.organization.id) as checkout:
            assert (checkout.path / "areas" / "analytics.md").is_file()

    def test_apply_changes_rejects_lint_violations_without_moving_head(self) -> None:
        config = store.initialize_repo(self.organization.id)

        def add_rogue_root_file(root: Path) -> None:
            (root / "secrets.txt").write_text("nope")

        with self.assertRaises(store.LintFailedError):
            store.apply_changes(self.organization.id, message="Add a rogue file", mutate=add_rogue_root_file)
        config.refresh_from_db()
        assert len(config.head_sha) == 40

    def test_apply_changes_noop_returns_current_head(self) -> None:
        config = store.initialize_repo(self.organization.id)
        head = store.apply_changes(self.organization.id, message="No changes", mutate=lambda root: None)
        assert head == config.head_sha

    def test_writer_lock_blocks_concurrent_writer_and_frees_on_exit(self) -> None:
        store.initialize_repo(self.organization.id)

        with store.repo_writer_lock(self.organization.id):
            with self.assertRaises(store.RepoLockUnavailableError):
                store.apply_changes(self.organization.id, message="Blocked", mutate=lambda root: None)

        head = store.apply_changes(self.organization.id, message="Unblocked", mutate=lambda root: None)
        assert head == ContextLayerConfig.objects.get(organization_id=self.organization.id).head_sha

    def test_purge_repo_history_keeps_tree_and_drops_history(self) -> None:
        store.initialize_repo(self.organization.id)

        def add_page(root: Path) -> None:
            (root / "areas").mkdir(exist_ok=True)
            (root / "areas" / "replay.md").write_text("# Replay\n")

        store.apply_changes(self.organization.id, message="Add the replay area page", mutate=add_page)
        store.purge_repo_history(self.organization.id)

        with store.checkout_repo(self.organization.id) as checkout:
            assert (checkout.path / "areas" / "replay.md").is_file()
            assert (checkout.path / "CLAUDE.md").is_symlink()
            commit_count = store._run_git(["rev-list", "--count", "HEAD"], cwd=checkout.path)
            assert commit_count == "1"

    def test_checkout_repo_without_config_raises(self) -> None:
        with self.assertRaises(store.RepoNotFoundError):
            with store.checkout_repo(self.organization.id):
                pass
