"""Unit tests for `freeze_templates_into_bundle`.

Stubs the janitor HTTP client with a simple capture object — these are
DB-only tests; the bundle write integration is exercised in
`services/agent-tests/`.
"""

from __future__ import annotations

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from django.db.models import ProtectedError

from parameterized import parameterized

from posthog.models import Team

from .models import (
    AgentApplication,
    AgentCustomToolTemplate,
    AgentRevision,
    AgentRevisionSkillTemplate,
    AgentSkillTemplate,
    AgentSkillTemplateFile,
)
from .registry_freeze import FreezeError, freeze_templates_into_bundle


class TestFreezeTemplatesIntoBundle(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.app = AgentApplication.objects.create(
            team=self.team,
            slug="test-app",
            name="Test App",
            description="",
        )
        self.revision = AgentRevision.objects.create(
            application=self.app,
            spec={},
            state="draft",
            bundle_uri="fs://test/",
        )
        self.janitor = MagicMock()

    def _skill(self, name: str = "s", body: str = "hello", version: int = 1) -> AgentSkillTemplate:
        return AgentSkillTemplate.objects.create(
            team=self.team,
            name=name,
            body=body,
            version=version,
            is_latest=True,
        )

    def _tool(self, name: str = "t", source: str = "x", compiled: str = "y") -> AgentCustomToolTemplate:
        return AgentCustomToolTemplate.objects.create(
            team=self.team,
            name=name,
            source=source,
            compiled_js=compiled,
            args_schema={},
            version=1,
            is_latest=True,
        )

    def _written(self, path: str) -> str:
        for call in self.janitor.put_file.call_args_list:
            if call.args[1] == path:
                return call.args[2]
        raise AssertionError(f"no put_file for {path!r}")

    # ---- happy path ----

    def test_no_refs_is_noop(self) -> None:
        self.revision.spec = {"model": "gpt-4", "skills": [], "tools": []}
        self.revision.save()
        result = freeze_templates_into_bundle(self.revision, self.janitor, team_id=self.team.pk)
        assert result.skill_refs == []
        assert result.custom_tool_refs == []
        assert result.native_tool_refs == []
        self.janitor.put_file.assert_not_called()

    def test_skill_ref_writes_bundle_and_inserts_join(self) -> None:
        skill = self._skill(name="research", body="# Research")
        self.revision.spec = {
            "skills": [{"from_template": str(skill.id), "alias": "research"}],
            "tools": [],
        }
        self.revision.save()
        result = freeze_templates_into_bundle(self.revision, self.janitor, team_id=self.team.pk)
        assert len(result.skill_refs) == 1
        ref = result.skill_refs[0]
        assert ref.pinned_version == 1
        assert ref.alias == "research"
        # Bundle write: a spec-compliant SKILL.md inside the skill's own dir.
        skill_md = self._written("skills/research/SKILL.md")
        assert "name: research" in skill_md
        assert "# Research" in skill_md

    def test_skill_with_files_writes_each_file(self) -> None:
        skill = self._skill(name="researchf", body="body")
        AgentSkillTemplateFile.objects.create(template=skill, path="examples/one.md", content="ex 1")
        AgentSkillTemplateFile.objects.create(template=skill, path="examples/two.md", content="ex 2")
        self.revision.spec = {
            "skills": [{"from_template": str(skill.id), "alias": "research"}],
        }
        self.revision.save()
        freeze_templates_into_bundle(self.revision, self.janitor, team_id=self.team.pk)
        rev_id = str(self.revision.id)
        self.janitor.put_file.assert_any_call(rev_id, "skills/research/examples/one.md", "ex 1")
        self.janitor.put_file.assert_any_call(rev_id, "skills/research/examples/two.md", "ex 2")

    def test_custom_tool_writes_source_and_compiled(self) -> None:
        tool = self._tool(name="stripe", source="export const x = 1", compiled="var x=1")
        self.revision.spec = {
            "tools": [{"kind": "custom_template", "from_template": str(tool.id), "alias": "stripe_lookup"}],
        }
        self.revision.save()
        result = freeze_templates_into_bundle(self.revision, self.janitor, team_id=self.team.pk)
        assert len(result.custom_tool_refs) == 1
        ref = result.custom_tool_refs[0]
        assert ref.alias == "stripe_lookup"
        rev_id = str(self.revision.id)
        self.janitor.put_file.assert_any_call(rev_id, "tools/stripe_lookup/source.ts", "export const x = 1")
        self.janitor.put_file.assert_any_call(rev_id, "tools/stripe_lookup/compiled.js", "var x=1")

    def test_native_tool_inserts_join_row_no_bundle_write(self) -> None:
        self.revision.spec = {
            "tools": [
                {"kind": "native", "id": "@posthog/query"},
                {"kind": "native", "id": "@posthog/load-skill"},
            ],
        }
        self.revision.save()
        result = freeze_templates_into_bundle(self.revision, self.janitor, team_id=self.team.pk)
        assert len(result.native_tool_refs) == 2
        ids = sorted(r.native_tool_id for r in result.native_tool_refs)
        assert ids == ["@posthog/load-skill", "@posthog/query"]
        # Native tools don't get bundle writes — they ship inside the runner.
        self.janitor.put_file.assert_not_called()

    # ---- version pinning ----

    def test_explicit_version_stamps_old_version(self) -> None:
        skill = self._skill(name="v1", body="v1 body", version=1)
        # Publish v2 manually.
        AgentSkillTemplate.objects.filter(pk=skill.pk).update(is_latest=False)
        AgentSkillTemplate.objects.create(
            team=self.team,
            name="v1",
            body="v2 body",
            version=2,
            is_latest=True,
        )
        self.revision.spec = {
            "skills": [{"from_template": str(skill.id), "version": 1, "alias": "pinned"}],
        }
        self.revision.save()
        result = freeze_templates_into_bundle(self.revision, self.janitor, team_id=self.team.pk)
        assert result.skill_refs[0].pinned_version == 1
        skill_md = self._written("skills/pinned/SKILL.md")
        assert "name: pinned" in skill_md
        assert "v1 body" in skill_md

    def test_omitted_version_stamps_latest(self) -> None:
        v1 = self._skill(name="lo", body="v1 body", version=1)
        AgentSkillTemplate.objects.filter(pk=v1.pk).update(is_latest=False)
        AgentSkillTemplate.objects.create(
            team=self.team,
            name="lo",
            body="v2 body",
            version=2,
            is_latest=True,
        )
        # Spec points at v1's id but no `version` — should still resolve to latest by name lineage.
        # Actually `from_template` is a row id; the test wires the v1 id but
        # the resolver looks up by pk. Refresh: use v2's id for the "latest" semantics.
        latest = AgentSkillTemplate.objects.get(name="lo", is_latest=True)
        self.revision.spec = {
            "skills": [{"from_template": str(latest.id), "alias": "lo"}],
        }
        self.revision.save()
        result = freeze_templates_into_bundle(self.revision, self.janitor, team_id=self.team.pk)
        assert result.skill_refs[0].pinned_version == 2

    def test_canonical_template_resolves_for_any_team(self) -> None:
        canonical = AgentSkillTemplate.objects.create(
            team=None,
            name="@posthog/research",
            body="canonical body",
            version=1,
            is_latest=True,
        )
        self.revision.spec = {
            "skills": [{"from_template": str(canonical.id), "alias": "research"}],
        }
        self.revision.save()
        freeze_templates_into_bundle(self.revision, self.janitor, team_id=self.team.pk)
        skill_md = self._written("skills/research/SKILL.md")
        assert "name: research" in skill_md
        assert "canonical body" in skill_md

    # ---- error paths ----

    def test_unknown_template_raises_freeze_error(self) -> None:
        self.revision.spec = {
            "skills": [{"from_template": "00000000-0000-0000-0000-000000000000", "alias": "ghost"}],
        }
        self.revision.save()
        with pytest.raises(FreezeError) as exc:
            freeze_templates_into_bundle(self.revision, self.janitor, team_id=self.team.pk)
        assert exc.value.kind == "skill"
        assert exc.value.index == 0

    def test_missing_alias_raises(self) -> None:
        skill = self._skill(name="alias-less", body="b")
        self.revision.spec = {
            "skills": [{"from_template": str(skill.id)}],  # no alias
        }
        self.revision.save()
        with pytest.raises(FreezeError) as exc:
            freeze_templates_into_bundle(self.revision, self.janitor, team_id=self.team.pk)
        assert "alias" in exc.value.message
        assert exc.value.index == 0

    @parameterized.expand(
        [
            ("traversal", "../escape"),
            ("nested", "a/b"),
            ("absolute", "/etc/passwd"),
            ("dot", "."),
            ("space", "bad alias"),
        ]
    )
    def test_unsafe_alias_raises(self, _name: str, alias: str) -> None:
        skill = self._skill(name="unsafe", body="b")
        self.revision.spec = {
            "skills": [{"from_template": str(skill.id), "alias": alias}],
        }
        self.revision.save()
        with pytest.raises(FreezeError) as exc:
            freeze_templates_into_bundle(self.revision, self.janitor, team_id=self.team.pk)
        assert exc.value.kind == "skill"
        # The bundle must not have been written with an escaping path.
        self.janitor.put_file.assert_not_called()

    def test_archived_template_not_resolvable(self) -> None:
        skill = self._skill(name="dead", body="b")
        AgentSkillTemplate.objects.filter(pk=skill.pk).update(deleted=True)
        self.revision.spec = {
            "skills": [{"from_template": str(skill.id), "alias": "dead"}],
        }
        self.revision.save()
        with pytest.raises(FreezeError):
            freeze_templates_into_bundle(self.revision, self.janitor, team_id=self.team.pk)

    def test_other_team_template_not_resolvable(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        skill = AgentSkillTemplate.objects.create(
            team=other_team,
            name="theirs",
            body="b",
            version=1,
            is_latest=True,
        )
        self.revision.spec = {
            "skills": [{"from_template": str(skill.id), "alias": "theirs"}],
        }
        self.revision.save()
        with pytest.raises(FreezeError):
            freeze_templates_into_bundle(self.revision, self.janitor, team_id=self.team.pk)

    # ---- idempotency + spec mutation ----

    def test_freeze_is_idempotent(self) -> None:
        skill = self._skill(name="rerun", body="b")
        self.revision.spec = {
            "skills": [{"from_template": str(skill.id), "alias": "r"}],
        }
        self.revision.save()
        freeze_templates_into_bundle(self.revision, self.janitor, team_id=self.team.pk)
        # Second freeze must not blow up on the unique-alias constraint.
        freeze_templates_into_bundle(self.revision, self.janitor, team_id=self.team.pk)
        assert AgentRevisionSkillTemplate.objects.filter(revision=self.revision).count() == 1

    def test_resolved_spec_carries_pinned_version_and_runtime_fields(self) -> None:
        skill = self._skill(name="stamp", body="b")
        self.revision.spec = {
            "skills": [{"from_template": str(skill.id), "alias": "s"}],
        }
        self.revision.save()
        result = freeze_templates_into_bundle(self.revision, self.janitor, team_id=self.team.pk)
        assert result.resolved_spec["skills"][0]["version"] == 1
        # Freeze also stamps the runtime fields the runner's zod schema requires.
        assert result.resolved_spec["skills"][0]["id"] == "s"
        assert result.resolved_spec["skills"][0]["path"] == "skills/s/SKILL.md"
        self.revision.refresh_from_db()
        assert self.revision.spec["skills"][0]["version"] == 1
        assert self.revision.spec["skills"][0]["id"] == "s"
        assert self.revision.spec["skills"][0]["path"] == "skills/s/SKILL.md"

    def test_custom_tool_freeze_reshapes_into_runtime_kind(self) -> None:
        tool = self._tool(name="reshape", source="ts", compiled="js")
        self.revision.spec = {
            "tools": [{"kind": "custom_template", "from_template": str(tool.id), "alias": "r"}],
        }
        self.revision.save()
        result = freeze_templates_into_bundle(self.revision, self.janitor, team_id=self.team.pk)
        # Runtime contract: kind=custom, id, path — what the runner dispatches against.
        entry = result.resolved_spec["tools"][0]
        assert entry["kind"] == "custom"
        assert entry["id"] == "r"
        assert entry["path"] == "tools/r/"
        # schema.json is written alongside source.ts + compiled.js.
        written_paths = sorted(call.args[1] for call in self.janitor.put_file.call_args_list)
        assert "tools/r/source.ts" in written_paths
        assert "tools/r/compiled.js" in written_paths
        assert "tools/r/schema.json" in written_paths

    # ---- hard-delete protection ----

    def test_hard_delete_blocked_after_freeze(self) -> None:
        skill = self._skill(name="locked", body="b")
        self.revision.spec = {
            "skills": [{"from_template": str(skill.id), "alias": "l"}],
        }
        self.revision.save()
        freeze_templates_into_bundle(self.revision, self.janitor, team_id=self.team.pk)
        # PROTECT on_delete prevents skill.delete() while a join row exists.
        with pytest.raises(ProtectedError):
            skill.delete()
