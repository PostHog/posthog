import tempfile
import subprocess
from pathlib import Path

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from redis.exceptions import RedisError

import posthog.storage.object_storage as object_storage_module
from posthog.storage.object_storage import UnavailableStorage

from products.context_layer.backend import repo_lint, store
from products.context_layer.backend.models import ContextLayerConfig


class TestRepoWriterLock(SimpleTestCase):
    def test_release_redis_error_does_not_propagate(self) -> None:
        client = MagicMock()
        client.set.return_value = True
        client.eval.side_effect = RedisError("redis unavailable")

        with patch.object(store, "get_client", return_value=client):
            # Releasing the lock fails, but the write has already landed by then,
            # so the context manager must exit cleanly rather than raise.
            with store.repo_writer_lock("org-1"):
                pass

        assert client.eval.called


class TestRunGit(SimpleTestCase):
    def test_missing_git_binary_raises_store_error(self) -> None:
        with patch.object(
            store.subprocess, "run", side_effect=FileNotFoundError(2, "No such file or directory", "git")
        ):
            with self.assertRaises(store.DependencyUnavailableError):
                store._run_git(["status"], cwd=Path("/tmp"))


class TestDreamPathGuard(SimpleTestCase):
    def test_allows_context_pages_and_rejects_server_owned_paths(self) -> None:
        assert store._dream_may_edit("org/strategy.md")
        assert store._dream_may_edit("areas/analytics.md")
        assert store._dream_may_edit("decisions/2026-08-23-pricing.md")
        assert store._dream_may_edit("projects/1/overview.md")
        assert store._dream_may_edit("projects/1/spaces/general.md")
        assert not store._dream_may_edit("projects/1/spaces/general.md", status="A")
        assert not store._dream_may_edit("projects/1/spaces/general.md", status="D")
        assert not store._dream_may_edit("AGENTS.md")
        assert not store._dream_may_edit("index.md")
        assert not store._dream_may_edit("projects/1/spaces/index.md")
        assert not store._dream_may_edit("scripts/lint")
        assert not store._dream_may_edit("scripts/publish")


class TestPruneBundles(SimpleTestCase):
    ORG = "11111111-1111-1111-1111-111111111111"

    def test_deletes_stale_bundles_and_never_the_kept_head(self) -> None:
        keep = "a" * 40
        stale = ["b" * 40, "c" * 40]
        listed = [store.bundle_key(self.ORG, sha) for sha in [keep, *stale]]

        with patch.object(store, "object_storage") as storage:
            storage.list_objects.return_value = listed
            storage.delete_objects.return_value = []
            store._prune_bundles_except(self.ORG, keep)

        storage.list_objects.assert_called_once_with(store.bundle_prefix(self.ORG))
        deleted = storage.delete_objects.call_args.args[0]
        assert set(deleted) == {store.bundle_key(self.ORG, sha) for sha in stale}
        assert store.bundle_key(self.ORG, keep) not in deleted

    def test_raises_when_a_bundle_delete_fails(self) -> None:
        keep = "a" * 40
        stale_key = store.bundle_key(self.ORG, "d" * 40)

        with patch.object(store, "object_storage") as storage:
            storage.list_objects.return_value = [store.bundle_key(self.ORG, keep), stale_key]
            storage.delete_objects.return_value = [stale_key]
            with self.assertRaises(store.PurgeIncompleteError):
                store._prune_bundles_except(self.ORG, keep)

    def test_raises_and_deletes_nothing_when_listing_unavailable(self) -> None:
        with patch.object(store, "object_storage") as storage:
            storage.list_objects.return_value = None
            with self.assertRaises(store.PurgeIncompleteError):
                store._prune_bundles_except(self.ORG, "a" * 40)
            storage.delete_objects.assert_not_called()


def _page(title: str) -> str:
    return f"---\nsummary: {title} page for store tests.\nstatus: active\n---\n# {title}\n"


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
            assert (checkout.path / "scripts" / "publish").is_file()

    def test_initialize_repo_is_idempotent(self) -> None:
        first = store.initialize_repo(self.organization.id)
        second = store.initialize_repo(self.organization.id)
        assert first.id == second.id
        assert first.head_sha == second.head_sha

    def test_apply_changes_lands_commit_and_moves_head(self) -> None:
        config = store.initialize_repo(self.organization.id)

        def add_area_page(root: Path) -> None:
            (root / "areas").mkdir(exist_ok=True)
            (root / "areas" / "analytics.md").write_text(_page("Analytics"))

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
            (root / "areas" / "replay.md").write_text(_page("Replay"))

        store.apply_changes(self.organization.id, message="Add the replay area page", mutate=add_page)
        store.purge_repo_history(self.organization.id)

        with store.checkout_repo(self.organization.id) as checkout:
            assert (checkout.path / "areas" / "replay.md").is_file()
            assert (checkout.path / "CLAUDE.md").is_symlink()
            commit_count = store._run_git(["rev-list", "--count", "HEAD"], cwd=checkout.path)
            assert commit_count == "1"

    def test_purge_prune_failure_stamps_the_config_until_a_purge_succeeds(self) -> None:
        store.initialize_repo(self.organization.id)
        scoped = MagicMock()
        capture = scoped.return_value.__enter__.return_value

        with (
            patch.object(store, "_prune_bundles_except", side_effect=store.PurgeIncompleteError("delete failed")),
            patch.object(store, "ph_scoped_capture", scoped),
        ):
            with self.assertRaises(store.PurgeIncompleteError):
                store.purge_repo_history(self.organization.id)

        config = ContextLayerConfig.objects.get(organization_id=self.organization.id)
        assert config.purge_incomplete_at is not None
        events = [call.kwargs["event"] for call in capture.call_args_list]
        assert "context layer purge incomplete" in events

        store.purge_repo_history(self.organization.id)
        config.refresh_from_db()
        assert config.purge_incomplete_at is None

    def test_landing_prunes_bundles_older_than_the_previous_head(self) -> None:
        h0 = store.initialize_repo(self.organization.id).head_sha

        def add_page(name: str):
            def mutate(root: Path) -> None:
                (root / "areas").mkdir(exist_ok=True)
                (root / "areas" / f"{name}.md").write_text(_page(name))

            return mutate

        h1 = store.apply_changes(self.organization.id, message="Add a", mutate=add_page("a"))
        h2 = store.apply_changes(self.organization.id, message="Add b", mutate=add_page("b"))

        assert object_storage_module.read_bytes(store.bundle_key(self.organization.id, h0), missing_ok=True) is None
        assert object_storage_module.read_bytes(store.bundle_key(self.organization.id, h1), missing_ok=True)
        assert object_storage_module.read_bytes(store.bundle_key(self.organization.id, h2), missing_ok=True)

    def test_landing_restores_tampered_scripts_to_canonical(self) -> None:
        store.initialize_repo(self.organization.id)

        def tamper(root: Path) -> None:
            (root / "scripts" / "lint").write_text("#!/bin/sh\necho pwned\n")
            (root / "areas").mkdir(exist_ok=True)
            (root / "areas" / "clean.md").write_text(_page("Clean"))

        store.apply_changes(self.organization.id, message="Edit with tampered script", mutate=tamper)

        with store.checkout_repo(self.organization.id) as checkout:
            shipped = (checkout.path / "scripts" / "lint").read_text()
            assert shipped == repo_lint._canonical_scripts()["lint"]

    def test_index_regeneration_never_writes_through_a_symlinked_index(self) -> None:
        store.initialize_repo(self.organization.id)
        victim = Path(tempfile.mkdtemp()) / "victim.txt"
        victim.write_text("untouched")

        def symlink_index(root: Path) -> None:
            index = root / "index.md"
            index.unlink()
            index.symlink_to(victim)
            (root / "areas").mkdir(exist_ok=True)
            (root / "areas" / "note.md").write_text(_page("Note"))

        store.apply_changes(self.organization.id, message="Symlink the index", mutate=symlink_index)

        assert victim.read_text() == "untouched"
        with store.checkout_repo(self.organization.id) as checkout:
            landed = checkout.path / "index.md"
            assert landed.is_file() and not landed.is_symlink()

    def test_refresh_never_writes_through_a_symlinked_script(self) -> None:
        store.initialize_repo(self.organization.id)
        victim = Path(tempfile.mkdtemp()) / "victim.txt"
        victim.write_text("untouched")

        def symlink_script(root: Path) -> None:
            lint = root / "scripts" / "lint"
            lint.unlink()
            lint.symlink_to(victim)

        store.apply_changes(self.organization.id, message="Symlink the linter", mutate=symlink_script)

        assert victim.read_text() == "untouched"
        with store.checkout_repo(self.organization.id) as checkout:
            landed = checkout.path / "scripts" / "lint"
            assert not landed.is_symlink()
            assert landed.read_text() == repo_lint._canonical_scripts()["lint"]

    def test_checkout_repo_without_config_raises(self) -> None:
        with self.assertRaises(store.RepoNotFoundError):
            with store.checkout_repo(self.organization.id):
                pass

    def _bundle_with_commits(self, commits: list[dict[str, str]]) -> bytes:
        with store.checkout_repo(self.organization.id) as checkout:
            env_git = ["git", "-c", "user.name=agent", "-c", "user.email=agent@example.com"]
            for index, files in enumerate(commits):
                for path, content in files.items():
                    target = checkout.path / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content)
                subprocess.run([*env_git, "add", "--all"], cwd=checkout.path, check=True)
                subprocess.run([*env_git, "commit", "--quiet", "-m", f"Edit {index}"], cwd=checkout.path, check=True)
            with tempfile.NamedTemporaryFile(suffix=".bundle") as bundle_file:
                subprocess.run(
                    [*env_git, "bundle", "create", bundle_file.name, "origin/main..main"],
                    cwd=checkout.path,
                    check=True,
                )
                return Path(bundle_file.name).read_bytes()

    def test_land_commit_bundle_rejects_a_tree_that_materializes_past_the_wiki_limit(self) -> None:
        # One 5 KB blob at 20 paths: deduplicated the objects stay tiny, but the
        # checkout writes 100 KB, so the limit only holds if it counts by path.
        store.initialize_repo(self.organization.id)
        bundle = self._bundle_with_commits([{f"areas/page-{index}.md": "x" * 5_000 for index in range(20)}])

        with patch.object(repo_lint, "MAX_TOTAL_BYTES", 60_000):
            # BundleConflictError rather than LintFailedError: an oversized tree
            # has to be rejected before it is ever checked out.
            with self.assertRaises(store.BundleConflictError) as caught:
                store.land_commit_bundle(self.organization.id, bundle)

        assert "checks out to more than" in str(caught.exception)

    def test_land_commit_bundle_rejects_a_bundle_past_the_cumulative_tree_budget(self) -> None:
        store.initialize_repo(self.organization.id)
        bundle = self._bundle_with_commits([{f"areas/page-{index}.md": "y" * 6_000} for index in range(3)])

        with patch.object(store, "BUNDLE_MAX_CUMULATIVE_TREE_BYTES", 30_000):
            with self.assertRaises(store.BundleConflictError) as caught:
                store.land_commit_bundle(self.organization.id, bundle)

        assert "several smaller bundles" in str(caught.exception)

    def test_land_dream_branch_rejects_server_owned_file_changes(self) -> None:
        store.initialize_repo(self.organization.id)
        branch = "dream/2026-08-23"
        with store.checkout_repo(self.organization.id) as checkout:
            env_git = ["git", "-c", "user.name=agent", "-c", "user.email=agent@example.com"]
            subprocess.run([*env_git, "checkout", "-q", "-b", branch], cwd=checkout.path, check=True)
            (checkout.path / "scripts" / "publish").write_text("#!/bin/sh\necho bypass\n")
            subprocess.run([*env_git, "add", "--all"], cwd=checkout.path, check=True)
            subprocess.run([*env_git, "commit", "--quiet", "-m", "Rewrite publisher"], cwd=checkout.path, check=True)
            with tempfile.NamedTemporaryFile(suffix=".bundle") as bundle_file:
                subprocess.run([*env_git, "bundle", "create", bundle_file.name, branch], cwd=checkout.path, check=True)
                bundle = Path(bundle_file.name).read_bytes()

        with self.assertRaises(store.BundleConflictError) as caught:
            store.land_dream_branch(self.organization.id, bundle, branch=branch)

        assert "scripts/publish" in str(caught.exception)
