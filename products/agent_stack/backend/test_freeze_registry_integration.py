"""
Integration test: AgentRevision freeze action ↔ registry template resolution.

Covers the Django side of the freeze flow end-to-end. The runtime side
(ingress + runner + bundle store) is exercised in `services/agent-tests/`
— this file guards the wiring between the registry tables and the
freeze action: template lookup, bundle copy via the janitor proxy,
join-row inserts inside a single transaction.

The janitor HTTP client is patched at the boundary so we don't need a
live `agent-janitor` process; the freeze action's call into
`janitor_client.freeze(...)` is verified by call assertions.
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.db.models import ProtectedError

from rest_framework import status

from .models import (
    AgentApplication,
    AgentCustomToolTemplate,
    AgentRevision,
    AgentRevisionCustomToolTemplate,
    AgentRevisionNativeTool,
    AgentRevisionSkillTemplate,
    AgentSkillTemplate,
    AgentSkillTemplateFile,
)


class TestFreezeRegistryIntegration(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.application = AgentApplication.objects.create(
            team=self.team,
            slug="freeze-int-agent",
            name="Freeze integration agent",
            description="",
        )
        self.freeze_url_base = f"/api/projects/{self.team.id}/agent_applications/{self.application.id}/revisions"

    def _make_revision(self, spec: dict) -> AgentRevision:
        return AgentRevision.objects.create(
            application=self.application,
            spec=spec,
            state="draft",
            bundle_uri="fs://test/",
        )

    def _make_skill(self, name: str, body: str, version: int = 1, is_latest: bool = True) -> AgentSkillTemplate:
        return AgentSkillTemplate.objects.create(
            team=self.team,
            name=name,
            body=body,
            version=version,
            is_latest=is_latest,
        )

    def _make_tool(self, name: str, source: str, compiled: str) -> AgentCustomToolTemplate:
        return AgentCustomToolTemplate.objects.create(
            team=self.team,
            name=name,
            source=source,
            compiled_js=compiled,
            args_schema={},
            version=1,
            is_latest=True,
        )

    # ---- happy path ----

    @patch("products.agent_stack.backend.api._janitor")
    def test_freeze_resolves_skill_ref_and_calls_janitor(self, mock_janitor: MagicMock) -> None:
        skill = self._make_skill("research", "# Research body")
        AgentSkillTemplateFile.objects.create(template=skill, path="examples/one.md", content="ex 1")
        revision = self._make_revision(
            {
                "skills": [{"from_template": str(skill.id), "alias": "research"}],
                "tools": [],
            }
        )
        mock_janitor.return_value.freeze.return_value = {"ok": True, "state": "ready", "bundle_sha256": "abc"}

        res = self.client.post(f"{self.freeze_url_base}/{revision.id}/freeze/")

        assert res.status_code == status.HTTP_200_OK, res.content
        # Bundle copies happened via the proxy. The SKILL.md is assembled
        # (frontmatter + body) and lives inside the skill's own directory.
        skill_md = next(
            c.args[2]
            for c in mock_janitor.return_value.put_file.call_args_list
            if c.args[1] == "skills/research/SKILL.md"
        )
        assert "name: research" in skill_md
        assert "# Research body" in skill_md
        mock_janitor.return_value.put_file.assert_any_call(str(revision.id), "skills/research/examples/one.md", "ex 1")
        # Final freeze step ran.
        mock_janitor.return_value.freeze.assert_called_once_with(str(revision.id))
        # Join row recorded the pinned version.
        join = AgentRevisionSkillTemplate.objects.get(revision=revision)
        assert join.pinned_version == 1
        assert join.alias == "research"
        # Spec carries the resolved version.
        revision.refresh_from_db()
        assert revision.spec["skills"][0]["version"] == 1

    @patch("products.agent_stack.backend.api._janitor")
    def test_freeze_resolves_custom_tool_and_native(self, mock_janitor: MagicMock) -> None:
        tool = self._make_tool("stripe", "src ts", "compiled js")
        revision = self._make_revision(
            {
                "skills": [],
                "tools": [
                    {"kind": "custom_template", "from_template": str(tool.id), "alias": "stripe_lookup"},
                    {"kind": "native", "id": "@posthog/query"},
                ],
            }
        )
        mock_janitor.return_value.freeze.return_value = {"ok": True}

        res = self.client.post(f"{self.freeze_url_base}/{revision.id}/freeze/")

        assert res.status_code == status.HTTP_200_OK, res.content
        mock_janitor.return_value.put_file.assert_any_call(str(revision.id), "tools/stripe_lookup/source.ts", "src ts")
        mock_janitor.return_value.put_file.assert_any_call(
            str(revision.id), "tools/stripe_lookup/compiled.js", "compiled js"
        )
        # Custom-tool join row.
        ct_join = AgentRevisionCustomToolTemplate.objects.get(revision=revision)
        assert ct_join.pinned_version == 1
        assert ct_join.alias == "stripe_lookup"
        # Native-tool join row.
        nt_join = AgentRevisionNativeTool.objects.get(revision=revision)
        assert nt_join.native_tool_id == "@posthog/query"

    @patch("products.agent_stack.backend.api._janitor")
    def test_freeze_with_no_template_refs_still_calls_janitor(self, mock_janitor: MagicMock) -> None:
        # Pre-template specs continue to work — the resolver no-ops.
        revision = self._make_revision({"model": "gpt-4", "skills": [], "tools": []})
        mock_janitor.return_value.freeze.return_value = {"ok": True}

        res = self.client.post(f"{self.freeze_url_base}/{revision.id}/freeze/")
        assert res.status_code == status.HTTP_200_OK, res.content
        mock_janitor.return_value.put_file.assert_not_called()
        mock_janitor.return_value.freeze.assert_called_once_with(str(revision.id))

    # ---- referential integrity ----

    @patch("products.agent_stack.backend.api._janitor")
    def test_hard_delete_blocked_after_freeze(self, mock_janitor: MagicMock) -> None:
        skill = self._make_skill("locked", "body")
        revision = self._make_revision(
            {
                "skills": [{"from_template": str(skill.id), "alias": "locked"}],
            }
        )
        mock_janitor.return_value.freeze.return_value = {"ok": True}

        self.client.post(f"{self.freeze_url_base}/{revision.id}/freeze/")

        # `on_delete=PROTECT` on the join FK prevents a hard-delete while
        # a frozen revision still pins the template.
        with self.assertRaises(ProtectedError):
            skill.delete()
        # Soft-delete (archive) remains legal — that's the prescribed path.
        skill.deleted = True
        skill.save(update_fields=["deleted"])

    # ---- latest-pin semantics ----

    @patch("products.agent_stack.backend.api._janitor")
    def test_latest_pin_uses_template_pk_not_lineage_name(self, mock_janitor: MagicMock) -> None:
        # Spec carries a specific template UUID. Even if a newer version lands
        # before freeze, the *resolved* row is the one identified by the PK —
        # so the pinned_version equals the row's own version.
        v1 = self._make_skill("ev", "v1", version=1, is_latest=False)
        v2 = AgentSkillTemplate.objects.create(
            team=self.team,
            name="ev",
            body="v2",
            version=2,
            is_latest=True,
        )
        # Spec points at v2's id — should resolve to v2 even without a `version` hint.
        revision = self._make_revision(
            {
                "skills": [{"from_template": str(v2.id), "alias": "ev"}],
            }
        )
        mock_janitor.return_value.freeze.return_value = {"ok": True}

        self.client.post(f"{self.freeze_url_base}/{revision.id}/freeze/")

        join = AgentRevisionSkillTemplate.objects.get(revision=revision)
        assert join.pinned_version == 2
        assert join.skill_template_id == v2.id
        # And v1 row remains untouched.
        v1.refresh_from_db()
        assert v1.version == 1

    # ---- error surfaces ----

    @patch("products.agent_stack.backend.api._janitor")
    def test_freeze_with_unknown_template_returns_400(self, mock_janitor: MagicMock) -> None:
        revision = self._make_revision(
            {
                "skills": [{"from_template": "00000000-0000-0000-0000-000000000000", "alias": "ghost"}],
            }
        )
        res = self.client.post(f"{self.freeze_url_base}/{revision.id}/freeze/")
        assert res.status_code == status.HTTP_400_BAD_REQUEST, res.content
        # The janitor's freeze should NOT have been called — we bailed before delegation.
        mock_janitor.return_value.freeze.assert_not_called()
