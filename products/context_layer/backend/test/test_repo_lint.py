import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from products.context_layer.backend.repo_lint import lint_repo
from products.context_layer.backend.scaffold import write_default_structure


def _remove_agents_md(root: Path) -> None:
    (root / "AGENTS.md").unlink()


def _claude_md_regular_file(root: Path) -> None:
    (root / "CLAUDE.md").unlink()
    (root / "CLAUDE.md").write_text("not a symlink")


def _rogue_root_file(root: Path) -> None:
    (root / "notes.md").write_text("# notes")


def _disallowed_root_directory(root: Path) -> None:
    (root / "attachments").mkdir()
    (root / "attachments" / "file.md").write_text("# file")


def _non_markdown_page(root: Path) -> None:
    (root / "areas").mkdir(exist_ok=True)
    (root / "areas" / "dump.json").write_text("{}")


def _misnamed_decision(root: Path) -> None:
    (root / "decisions").mkdir(exist_ok=True)
    (root / "decisions" / "pricing.md").write_text("# pricing")


def _channel_page_without_channel_id(root: Path) -> None:
    (root / "channels").mkdir(exist_ok=True)
    (root / "channels" / "general.md").write_text("---\nowner: someone\n---\n# general")


def _stray_symlink(root: Path) -> None:
    (root / "areas").mkdir(exist_ok=True)
    (root / "areas" / "alias.md").symlink_to("../AGENTS.md")


def _oversized_page(root: Path) -> None:
    (root / "areas").mkdir(exist_ok=True)
    (root / "areas" / "huge.md").write_text("x" * 1_000_001)


class TestRepoLint(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.root = Path(tempfile.mkdtemp(prefix="context-layer-lint-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        write_default_structure(self.root)

    def test_default_structure_is_clean(self) -> None:
        assert lint_repo(self.root) == []

    def test_valid_pages_in_every_directory_are_clean(self) -> None:
        (self.root / "areas").mkdir()
        (self.root / "areas" / "analytics.md").write_text("# analytics")
        (self.root / "decisions").mkdir()
        (self.root / "decisions" / "2026-08-18-pricing-tiers.md").write_text("# pricing tiers")
        (self.root / "channels").mkdir()
        (self.root / "channels" / "general.md").write_text("---\nchannel_id: abc123\n---\n# general")
        assert lint_repo(self.root) == []

    @parameterized.expand(
        [
            ("missing_agents_md", _remove_agents_md),
            ("claude_md_regular_file", _claude_md_regular_file),
            ("rogue_root_file", _rogue_root_file),
            ("disallowed_root_directory", _disallowed_root_directory),
            ("non_markdown_page", _non_markdown_page),
            ("misnamed_decision", _misnamed_decision),
            ("channel_page_without_channel_id", _channel_page_without_channel_id),
            ("stray_symlink", _stray_symlink),
            ("oversized_page", _oversized_page),
        ]
    )
    def test_violations_are_reported(self, _name: str, violate: Callable[[Path], None]) -> None:
        violate(self.root)
        assert lint_repo(self.root) != []
