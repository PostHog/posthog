import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import Organization, Team

from products.agent_memory.backend import logic
from products.agent_memory.backend.models import AgentMemoryFile


class TestPathNormalization(BaseTest):
    @parameterized.expand(
        [
            ("project.md", "project.md"),
            ("/project.md", "project.md"),
            ("  project.md  ", "project.md"),
            ("users/jane-doe.md", "users/jane-doe.md"),
            ("scouts/signals-scout-errors/scratchpad.md", "scouts/signals-scout-errors/scratchpad.md"),
            ("users//jane.md", "users/jane.md"),
        ]
    )
    def test_normalizes_valid_paths(self, raw: str, expected: str) -> None:
        assert logic.normalize_path(raw) == expected

    @parameterized.expand(
        [
            ("",),
            ("   ",),
            ("/",),
            ("project.txt",),
            ("project",),
            ("../secret.md",),
            ("users/../../escape.md",),
            ("users/./jane.md",),
            ("users/ja ne.md",),
        ]
    )
    def test_rejects_invalid_paths(self, raw: str) -> None:
        with pytest.raises(logic.InvalidMemoryPathError):
            logic.normalize_path(raw)


class TestMemoryStore(BaseTest):
    def test_create_then_read(self) -> None:
        row = logic.write_memory(team_id=self.team.id, path="project.md", content="# Project", expected_version=None)
        assert row.version == 1
        assert row.content == "# Project"

        read = logic.read_memory(team_id=self.team.id, path="project.md")
        assert read.id == row.id
        assert read.content == "# Project"

    def test_read_missing_raises(self) -> None:
        with pytest.raises(logic.MemoryFileNotFoundError):
            logic.read_memory(team_id=self.team.id, path="absent.md")

    def test_create_when_already_exists_conflicts(self) -> None:
        logic.write_memory(team_id=self.team.id, path="project.md", content="a", expected_version=None)
        with pytest.raises(logic.MemoryVersionConflictError) as exc:
            logic.write_memory(team_id=self.team.id, path="project.md", content="b", expected_version=None)
        assert exc.value.actual_version == 1

    def test_cas_update_success_bumps_version(self) -> None:
        logic.write_memory(team_id=self.team.id, path="project.md", content="v1", expected_version=None)
        updated = logic.write_memory(team_id=self.team.id, path="project.md", content="v2", expected_version=1)
        assert updated.version == 2
        assert updated.content == "v2"

    def test_cas_update_stale_version_conflicts(self) -> None:
        logic.write_memory(team_id=self.team.id, path="project.md", content="v1", expected_version=None)
        logic.write_memory(team_id=self.team.id, path="project.md", content="v2", expected_version=1)
        # Caller still holds version 1 — must be rejected with the real stored version.
        with pytest.raises(logic.MemoryVersionConflictError) as exc:
            logic.write_memory(team_id=self.team.id, path="project.md", content="v3-stale", expected_version=1)
        assert exc.value.expected_version == 1
        assert exc.value.actual_version == 2
        # The losing write must not have mutated the file.
        assert logic.read_memory(team_id=self.team.id, path="project.md").content == "v2"

    def test_update_nonexistent_file_conflicts(self) -> None:
        with pytest.raises(logic.MemoryVersionConflictError) as exc:
            logic.write_memory(team_id=self.team.id, path="ghost.md", content="x", expected_version=3)
        assert exc.value.actual_version == 0

    def test_content_too_large_rejected(self) -> None:
        oversized = "x" * (logic.MAX_FILE_BYTES + 1)
        with pytest.raises(logic.MemoryContentTooLargeError):
            logic.write_memory(team_id=self.team.id, path="big.md", content=oversized, expected_version=None)

    def test_delete_returns_true_then_false(self) -> None:
        logic.write_memory(team_id=self.team.id, path="project.md", content="a", expected_version=None)
        assert logic.delete_memory(team_id=self.team.id, path="project.md") is True
        assert logic.delete_memory(team_id=self.team.id, path="project.md") is False
        with pytest.raises(logic.MemoryFileNotFoundError):
            logic.read_memory(team_id=self.team.id, path="project.md")


class TestAppendSection(BaseTest):
    def test_append_to_new_file_creates_it(self) -> None:
        row = logic.append_section(
            team_id=self.team.id, path="project.md", heading="Conventions", body="Use snake_case."
        )
        assert row.version == 1
        assert "## Conventions" in row.content
        assert "Use snake_case." in row.content

    def test_append_new_section_preserves_existing(self) -> None:
        logic.append_section(team_id=self.team.id, path="project.md", heading="A", body="alpha")
        row = logic.append_section(team_id=self.team.id, path="project.md", heading="B", body="beta")
        assert "## A" in row.content
        assert "alpha" in row.content
        assert "## B" in row.content
        assert "beta" in row.content
        assert row.version == 2

    def test_append_existing_heading_replaces_only_that_section(self) -> None:
        logic.append_section(team_id=self.team.id, path="project.md", heading="A", body="alpha-old")
        logic.append_section(team_id=self.team.id, path="project.md", heading="B", body="beta")
        row = logic.append_section(team_id=self.team.id, path="project.md", heading="A", body="alpha-new")
        assert "alpha-new" in row.content
        assert "alpha-old" not in row.content
        # B is untouched.
        assert "beta" in row.content

    def test_append_matches_heading_case_insensitively_and_any_level(self) -> None:
        logic.write_memory(
            team_id=self.team.id,
            path="project.md",
            content="# Notes\n\nfreeform\n\n### Findings\n\nold finding\n",
            expected_version=None,
        )
        row = logic.append_section(team_id=self.team.id, path="project.md", heading="findings", body="new finding")
        assert "new finding" in row.content
        assert "old finding" not in row.content
        # Pre-existing freeform content above the section survives.
        assert "freeform" in row.content
        # The original heading level (###) is preserved.
        assert "### Findings" in row.content

    def test_append_empty_heading_rejected(self) -> None:
        with pytest.raises(logic.InvalidMemoryPathError):
            logic.append_section(team_id=self.team.id, path="project.md", heading="  ", body="x")


class TestListMemory(BaseTest):
    def _seed(self) -> None:
        for path in ["project.md", "users/jane.md", "users/john.md", "scouts/errors/scratchpad.md"]:
            logic.write_memory(team_id=self.team.id, path=path, content="x", expected_version=None)

    def test_list_all_sorted(self) -> None:
        self._seed()
        rows = logic.list_memory(team_id=self.team.id)
        assert [r.path for r in rows] == [
            "project.md",
            "scouts/errors/scratchpad.md",
            "users/jane.md",
            "users/john.md",
        ]

    @parameterized.expand(
        [
            ("users/", ["users/jane.md", "users/john.md"]),
            ("scouts/", ["scouts/errors/scratchpad.md"]),
            ("project", ["project.md"]),
        ]
    )
    def test_list_with_prefix(self, prefix: str, expected: list[str]) -> None:
        self._seed()
        rows = logic.list_memory(team_id=self.team.id, prefix=prefix)
        assert sorted(r.path for r in rows) == sorted(expected)


class TestTeamIsolation(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.other_org = Organization.objects.create(name="Other")
        self.other_team = Team.objects.create(organization=self.other_org, name="Other team")

    def test_files_are_team_scoped(self) -> None:
        logic.write_memory(team_id=self.team.id, path="project.md", content="ours", expected_version=None)
        logic.write_memory(team_id=self.other_team.id, path="project.md", content="theirs", expected_version=None)

        ours = logic.read_memory(team_id=self.team.id, path="project.md")
        theirs = logic.read_memory(team_id=self.other_team.id, path="project.md")
        assert ours.content == "ours"
        assert theirs.content == "theirs"
        assert ours.id != theirs.id

    def test_other_team_cannot_read_our_file(self) -> None:
        logic.write_memory(team_id=self.team.id, path="secret.md", content="ours", expected_version=None)
        with pytest.raises(logic.MemoryFileNotFoundError):
            logic.read_memory(team_id=self.other_team.id, path="secret.md")

    def test_list_does_not_leak_across_teams(self) -> None:
        logic.write_memory(team_id=self.team.id, path="a.md", content="x", expected_version=None)
        logic.write_memory(team_id=self.other_team.id, path="b.md", content="y", expected_version=None)
        assert [r.path for r in logic.list_memory(team_id=self.team.id)] == ["a.md"]
        assert [r.path for r in logic.list_memory(team_id=self.other_team.id)] == ["b.md"]

    def test_same_path_different_teams_no_unique_collision(self) -> None:
        logic.write_memory(team_id=self.team.id, path="project.md", content="x", expected_version=None)
        logic.write_memory(team_id=self.other_team.id, path="project.md", content="y", expected_version=None)
        assert AgentMemoryFile.objects.unscoped().filter(path="project.md").count() == 2
