import uuid
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from products.context_layer.backend.repo_lint import lint_repo, report_repo
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
    spaces = root / "projects" / "1" / "spaces"
    spaces.mkdir(parents=True, exist_ok=True)
    (spaces / "general.md").write_text("---\nteam_id: 1\nowner: someone\n---\n# general")


def _channel_page_with_empty_channel_id(root: Path) -> None:
    spaces = root / "projects" / "1" / "spaces"
    spaces.mkdir(parents=True, exist_ok=True)
    (spaces / "general.md").write_text("---\nteam_id: 1\nchannel_id:   \n---\n# general")


def _channel_page_with_noncanonical_channel_id(root: Path) -> None:
    spaces = root / "projects" / "1" / "spaces"
    spaces.mkdir(parents=True, exist_ok=True)
    # A valid UUID in a spelling Django never serves; resolution would never match it.
    (spaces / "general.md").write_text(f"---\nteam_id: 1\nchannel_id: {str(uuid.uuid4()).upper()}\n---\n# general")


def _stray_symlink(root: Path) -> None:
    (root / "areas").mkdir(exist_ok=True)
    (root / "areas" / "alias.md").symlink_to("../AGENTS.md")


def _index_symlink(root: Path) -> None:
    (root / "index.md").unlink()
    (root / "index.md").symlink_to("/tmp/victim")


def _oversized_page(root: Path) -> None:
    (root / "areas").mkdir(exist_ok=True)
    (root / "areas" / "huge.md").write_text(
        "---\nsummary: Huge\nstatus: active\nsources: test\n---\n# Huge\n" + "x" * 16_001
    )


def _space_page_with_mismatched_team_id(root: Path) -> None:
    spaces = root / "projects" / "1" / "spaces"
    spaces.mkdir(parents=True, exist_ok=True)
    (spaces / "general.md").write_text(
        f"---\nteam_id: 2\nchannel_id: {uuid.uuid4()}\nsummary: General\nstatus: active\n---\n# general"
    )


def _scripts_symlink(root: Path) -> None:
    (root / "scripts" / "alias").symlink_to("/etc/hosts")


def _scripts_extra_file(root: Path) -> None:
    (root / "scripts" / "deploy.sh").write_text("#!/bin/sh\n")


def _non_utf8_page(root: Path) -> None:
    (root / "areas").mkdir(exist_ok=True)
    (root / "areas" / "pricing.md").write_bytes(b"# Pricing\n\nCaf\xe9 tier costs \x80100.\n")


def _scripts_tampered_lint(root: Path) -> None:
    lint = root / "scripts" / "lint"
    lint.write_text(lint.read_text() + "\nimport os  # smuggled\n")


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
        (self.root / "areas" / "analytics.md").write_text(
            "---\nsummary: Analytics\nstatus: active\nsources: test\n---\n# analytics"
        )
        (self.root / "decisions").mkdir()
        (self.root / "decisions" / "2026-08-18-pricing-tiers.md").write_text(
            "---\nsummary: Pricing\nstatus: active\nsources: test\n---\n# pricing tiers"
        )
        spaces = self.root / "projects" / "1" / "spaces"
        spaces.mkdir(parents=True)
        (spaces / "general.md").write_text(
            f"---\nteam_id: 1\nchannel_id: {uuid.uuid4()}\nsummary: General\nstatus: active\nsources: test\n---\n# general"
        )
        assert lint_repo(self.root) == []

    def test_report_findings_do_not_fail_lint(self) -> None:
        _oversized_page(self.root)
        assert lint_repo(self.root) == []
        assert any(finding.startswith("oversized:") for finding in report_repo(self.root))

    def test_channel_ids_must_be_unique_uuids(self) -> None:
        channels = self.root / "projects" / "1" / "spaces"
        channels.mkdir(parents=True)
        channel_id = uuid.uuid4()
        metadata = "team_id: 1\nsummary: Channel\nstatus: active\nsources: test"
        (channels / "one.md").write_text(f"---\nchannel_id: {channel_id}\n{metadata}\n---\n# one")
        (channels / "two.md").write_text(f"---\nchannel_id: {channel_id}\n{metadata}\n---\n# two")
        (channels / "invalid.md").write_text(f"---\nchannel_id: not-a-uuid\n{metadata}\n---\n# invalid")

        errors = lint_repo(self.root)

        assert any("must be a UUID" in error for error in errors)
        assert any("appears in more than one page" in error for error in errors)

    @parameterized.expand(
        [
            ("missing_agents_md", _remove_agents_md),
            ("claude_md_regular_file", _claude_md_regular_file),
            ("rogue_root_file", _rogue_root_file),
            ("disallowed_root_directory", _disallowed_root_directory),
            ("non_markdown_page", _non_markdown_page),
            ("misnamed_decision", _misnamed_decision),
            ("channel_page_without_channel_id", _channel_page_without_channel_id),
            ("channel_page_with_empty_channel_id", _channel_page_with_empty_channel_id),
            ("channel_page_with_noncanonical_channel_id", _channel_page_with_noncanonical_channel_id),
            ("space_page_with_mismatched_team_id", _space_page_with_mismatched_team_id),
            ("stray_symlink", _stray_symlink),
            ("index_symlink", _index_symlink),
            ("scripts_symlink", _scripts_symlink),
            ("scripts_extra_file", _scripts_extra_file),
            ("scripts_tampered_lint", _scripts_tampered_lint),
            ("non_utf8_page", _non_utf8_page),
        ]
    )
    def test_violations_are_reported(self, _name: str, violate: Callable[[Path], None]) -> None:
        violate(self.root)
        assert lint_repo(self.root) != []
