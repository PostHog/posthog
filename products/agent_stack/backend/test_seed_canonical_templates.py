"""Tests for `manage.py seed_canonical_templates`.

Uses a tmp source dir with mocked markdown files — avoids coupling the
test to the actual vendored canonical content (which may evolve).
"""

from __future__ import annotations

import tempfile
from io import StringIO
from pathlib import Path

from posthog.test.base import BaseTest

from django.core.management import call_command

from .models import AgentSkillTemplate, AgentSkillTemplateFile


class TestSeedCanonicalTemplates(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.tmpdir = Path(tempfile.mkdtemp())
        (self.tmpdir / "skills").mkdir()

    def _write(self, name: str, content: str) -> None:
        (self.tmpdir / "skills" / name).write_text(content)

    def _write_multifile(self, slug: str, body: str, files: dict[str, str]) -> None:
        d = self.tmpdir / "skills" / slug
        d.mkdir()
        (d / "SKILL.md").write_text(body)
        for path, content in files.items():
            target = d / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

    def _run(self, *, dry_run: bool = False) -> str:
        out = StringIO()
        call_command(
            "seed_canonical_templates",
            path=str(self.tmpdir),
            dry_run=dry_run,
            stdout=out,
        )
        return out.getvalue()

    def test_single_file_skill_inserts(self) -> None:
        self._write("research.md", "---\ndescription: How to research\nversion: 1\n---\nbody here")
        self._run()
        row = AgentSkillTemplate.objects.get(team__isnull=True, name="@posthog/research")
        assert row.body == "body here"
        assert row.description == "How to research"
        assert row.version == 1
        assert row.is_latest is True

    def test_multifile_skill_inserts_companions(self) -> None:
        self._write_multifile(
            "with-files",
            "---\ndescription: multi\nversion: 1\n---\nbody",
            {"examples/one.md": "ex1", "examples/two.md": "ex2"},
        )
        self._run()
        row = AgentSkillTemplate.objects.get(team__isnull=True, name="@posthog/with-files")
        paths = sorted(f.path for f in row.files.all())
        assert paths == ["examples/one.md", "examples/two.md"]

    def test_no_frontmatter_uses_defaults(self) -> None:
        self._write("bare.md", "just a body")
        self._run()
        row = AgentSkillTemplate.objects.get(team__isnull=True, name="@posthog/bare")
        assert row.body == "just a body"
        assert row.description == ""
        assert row.version == 1

    def test_dry_run_does_not_persist(self) -> None:
        self._write("dry.md", "---\ndescription: x\nversion: 1\n---\nbody")
        out = self._run(dry_run=True)
        assert "Would create 1" in out
        assert not AgentSkillTemplate.objects.filter(name="@posthog/dry").exists()

    def test_rerun_is_noop_when_unchanged(self) -> None:
        self._write("stable.md", "---\nversion: 1\n---\nbody")
        self._run()
        out = self._run()
        assert "leave 1 unchanged" in out

    def test_rerun_updates_when_body_changes(self) -> None:
        self._write("evolving.md", "---\nversion: 1\n---\nv1 body")
        self._run()
        # Same version, new body.
        self._write("evolving.md", "---\nversion: 1\n---\nv1 body (edited)")
        out = self._run()
        assert "update 1" in out
        row = AgentSkillTemplate.objects.get(name="@posthog/evolving")
        assert row.body == "v1 body (edited)"

    def test_bump_version_creates_new_row(self) -> None:
        self._write("bumped.md", "---\nversion: 1\n---\nv1")
        self._run()
        self._write("bumped.md", "---\nversion: 2\n---\nv2 body")
        self._run()
        rows = AgentSkillTemplate.objects.filter(name="@posthog/bumped", deleted=False).order_by("version")
        assert [r.version for r in rows] == [1, 2]
        assert rows[1].is_latest is True
        assert rows[0].is_latest is False

    def test_rerun_replaces_companion_files(self) -> None:
        self._write_multifile(
            "files",
            "---\nversion: 1\n---\nbody",
            {"a.md": "alpha"},
        )
        self._run()
        # Drop a, add b.
        # `_write_multifile` mkdirs again — easier to manipulate files directly.
        d = self.tmpdir / "skills" / "files"
        (d / "a.md").unlink()
        (d / "b.md").write_text("beta")
        out = self._run()
        assert "update 1" in out
        paths = sorted(
            AgentSkillTemplateFile.objects.filter(template__name="@posthog/files").values_list("path", flat=True)
        )
        assert paths == ["b.md"]
