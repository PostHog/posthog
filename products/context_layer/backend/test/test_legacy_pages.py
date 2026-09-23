import tempfile
from pathlib import Path

from unittest import TestCase

from products.context_layer.backend.legacy_pages import migrate_legacy_channel_pages
from products.context_layer.backend.repo_lint import lint_repo
from products.context_layer.backend.scaffold import write_default_structure
from products.context_layer.backend.store import LintFailedError


class TestLegacyChannelPages(TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        write_default_structure(self.root)
        self.channel_id = "cdfdbb23-cc3e-4aa7-8ebe-a2a438cd617a"
        self.content = f"---\nsummary: Release checks.\nstatus: active\nchannel_id: {self.channel_id}\n---\n# Releases\nKeep the release checklist.\n"
        (self.root / "channels").mkdir()
        (self.root / "channels/releases.md").write_text(self.content)

    def test_upgrade_preserves_content_and_links_and_is_idempotent(self) -> None:
        overview = self.root / "org/overview.md"
        overview.write_text(overview.read_text() + "\n[[channels/releases#Releases|Release checks]]\n")

        migrate_legacy_channel_pages(self.root, {self.channel_id: 123})

        destination = self.root / "projects/123/spaces/releases.md"
        assert destination.read_text() == self.content.replace("---\n", "---\nteam_id: 123\n", 1)
        assert "[[projects/123/spaces/releases#Releases|Release checks]]" in overview.read_text()
        assert not (self.root / "channels").exists()
        assert lint_repo(self.root) == []
        assert migrate_legacy_channel_pages(self.root, {self.channel_id: 123}) == []

    def test_unknown_channel_is_preserved_for_manual_repair(self) -> None:
        with self.assertRaises(LintFailedError):
            migrate_legacy_channel_pages(self.root, {})
        assert (self.root / "channels/releases.md").read_text() == self.content

    def test_missing_channel_id_is_reported_before_moving_pages(self) -> None:
        source = self.root / "channels/releases.md"
        content = self.content.replace(f"channel_id: {self.channel_id}\n", "")
        source.write_text(content)
        with self.assertRaisesRegex(LintFailedError, "channel_id is required"):
            migrate_legacy_channel_pages(self.root, {self.channel_id: 123})
        assert source.read_text() == content

    def test_existing_destination_is_not_overwritten(self) -> None:
        destination = self.root / "projects/123/spaces/releases.md"
        destination.parent.mkdir(parents=True)
        destination.write_text("Existing page")
        with self.assertRaises(LintFailedError):
            migrate_legacy_channel_pages(self.root, {self.channel_id: 123})
        assert destination.read_text() == "Existing page"
        assert (self.root / "channels/releases.md").read_text() == self.content

    def test_symlinked_destination_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            (self.root / "projects").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(LintFailedError):
                migrate_legacy_channel_pages(self.root, {self.channel_id: 123})
            assert list(Path(outside).iterdir()) == []
