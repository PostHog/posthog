import os
import uuid
import shutil
import tempfile
import subprocess
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


class TestWikiPublish(SimpleTestCase):
    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.root, env=self.env, check=True, capture_output=True, text=True
        ).stdout.strip()

    def setUp(self) -> None:
        super().setUp()
        self.workspace = Path(tempfile.mkdtemp(prefix="context-layer-publish-"))
        self.addCleanup(shutil.rmtree, self.workspace, ignore_errors=True)
        self.root = self.workspace / "wiki"
        self.root.mkdir()
        write_default_structure(self.root)
        self.bin_dir = self.workspace / "bin"
        self.bin_dir.mkdir()
        (self.bin_dir / "curl").write_text(
            """#!/bin/sh
for arg do
    printf '<%s>\\n' "$arg"
    case "$arg" in
        bundle=@*) cp "${arg#bundle=@}" "$PUBLISH_BUNDLE_PATH" ;;
    esac
done
exit "${PUBLISH_HTTP_EXIT:-0}"
"""
        )
        (self.bin_dir / "curl").chmod(0o755)
        self.summary_file = self.workspace / "dream summary.md"
        self.summary_file.write_text("Reviewed recent activity\nRemoved an expired priority")
        self.bundle = self.workspace / "received.bundle"
        self.env = {
            **os.environ,
            "PATH": f"{self.bin_dir}:{os.environ['PATH']}",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "POSTHOG_API_URL": "https://example.com",
            "POSTHOG_PERSONAL_API_KEY": "test-key",
            "POSTHOG_CONTEXT_LAYER_COMMITS_PATH": "/commits/",
            "PUBLISH_BUNDLE_PATH": str(self.bundle),
        }
        self._git("init", "--initial-branch=main")
        self._git("config", "user.name", "Wiki test")
        self._git("config", "user.email", "wiki@example.com")
        self._git("add", "--all")
        self._git("commit", "-m", "Seed wiki")
        self._git("update-ref", "refs/remotes/origin/main", "HEAD")
        self._git("remote", "add", "origin", str(self.workspace / "context.bundle"))

    def _publish(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.root / "scripts" / "publish", *args, self.summary_file],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
        )

    @parameterized.expand([("unstaged",), ("staged",), ("committed",)])
    def test_publish_sends_wiki_edits_and_summary_contents_as_text(self, change_state: str) -> None:
        (self.root / "areas").mkdir()
        page = self.root / "areas" / "analytics.md"
        page.write_text("---\nsummary: Analytics\nstatus: active\nsources: test\n---\n# Analytics\n")
        if change_state in ("staged", "committed"):
            self._git("add", "--all")
        if change_state == "committed":
            self._git("checkout", "-b", "dream/2026-09-01")
            self._git("commit", "-m", "Add analytics context")
        self._git("config", "commit.gpgsign", "true")
        self._git("config", "gpg.program", "/nonexistent/gpg")

        result = self._publish("--dream")

        assert result.returncode == 0, result.stderr
        assert "<--form-string>\n<summary=Reviewed recent activity\nRemoved an expired priority>" in result.stdout
        assert "publish: landed" in result.stdout
        assert self._git("status", "--porcelain") == ""
        assert self._git("branch", "--show-current").startswith("dream/")
        self._git("bundle", "verify", str(self.bundle))
        self._git("fetch", str(self.bundle), self._git("branch", "--show-current"))
        assert self._git("show", "FETCH_HEAD:areas/analytics.md") == page.read_text().strip()

    def test_publish_reports_no_changes_without_uploading(self) -> None:
        result = self._publish("--dream")

        assert result.returncode == 0, result.stderr
        assert "publish: no changes" in result.stdout
        assert not self.bundle.exists()

    def test_publish_does_not_hide_bundle_errors(self) -> None:
        self._git("update-ref", "-d", "refs/remotes/origin/main")

        result = self._publish("--dream")

        assert result.returncode != 0
        assert "publish: landed" not in result.stdout
        assert not self.bundle.exists()

    def test_publish_does_not_report_a_rejected_upload_as_landed(self) -> None:
        self._git("checkout", "-b", "dream/2026-09-01")
        self._git("commit", "--allow-empty", "-m", "Review wiki")
        self.env["PUBLISH_HTTP_EXIT"] = "22"

        result = self._publish("--dream")

        assert result.returncode != 0
        assert "publish: landed" not in result.stdout

    def test_publish_refuses_invalid_content_before_committing(self) -> None:
        (self.root / "notes.md").write_text("# Unscoped notes")
        original_head = self._git("rev-parse", "HEAD")

        result = self._publish("--dream")

        assert result.returncode != 0
        assert self._git("rev-parse", "HEAD") == original_head
        assert not self.bundle.exists()
