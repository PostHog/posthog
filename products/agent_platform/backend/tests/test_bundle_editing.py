"""
PUT  /revisions/<id>/bundle/file/    — single .md file update
POST /revisions/<id>/bundle/import/  — bulk import

`agent.md` writes proxy to the janitor (mocked here at the client boundary).
Skill writes are store-backed: they publish new llma-skill store versions and
re-pin the draft's `skill_refs` — asserted against real store rows. What we
assert is the Django-side contract: draft-only gating, path / id validation,
store versioning + ref pinning, and the llm_skill:write scope boundary.
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.skills.backend.models.skills import LLMSkill

from ee.models.rbac.access_control import AccessControl

from ..logic.kernel_skills import all_kernel_skill_ids
from ..models import AgentApplication, AgentRevision

NON_DRAFT_STATES = [("ready",), ("live",), ("archived",)]


class TestBundleEditing(APIBaseTest):
    databases = {
        "default",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def setUp(self) -> None:
        super().setUp()
        self.application = AgentApplication.all_teams.create(
            team_id=self.team.id,
            slug="growth-agent",
            name="Growth agent",
            description="",
        )
        self.skill = LLMSkill.objects.create(
            team=self.team,
            name="growth-review",
            description="Original description",
            body="The original body.",
        )

    def _revision(self, state: str = "draft", skill_refs: list[dict] | None = None) -> AgentRevision:
        return AgentRevision.all_teams.create(
            application=self.application,
            team_id=self.team.id,
            state=state,
            spec={},
            skill_refs=(
                skill_refs if skill_refs is not None else [{"from_template": "growth-review", "alias": "growth-review"}]
            ),
            # `ready`/`live` rows in prod carry a stamped sha; supply one so the
            # row looks real even though we only need the state for the gate.
            bundle_sha256=("a" * 64) if state in {"ready", "live", "archived"} else None,
        )

    def _file_url(self, revision: AgentRevision) -> str:
        return (
            f"/api/projects/{self.team.id}/agent_applications/{self.application.id}"
            f"/revisions/{revision.id}/bundle/file/"
        )

    def _import_url(self, revision: AgentRevision) -> str:
        return (
            f"/api/projects/{self.team.id}/agent_applications/{self.application.id}"
            f"/revisions/{revision.id}/bundle/import/"
        )

    def _latest(self, name: str = "growth-review") -> LLMSkill:
        return LLMSkill.objects.get(team=self.team, name=name, is_latest=True, deleted=False)

    def _bearer_client(self, scopes: list[str]) -> APIClient:
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="agent-key", user=self.user, secure_value=hash_key_value(raw), scopes=scopes
        )
        client = APIClient()  # no session — only the Bearer token authenticates
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        return client

    # ── single-file PUT ────────────────────────────────────────────────────

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_put_agent_md_on_draft(self, mock_janitor: MagicMock) -> None:
        revision = self._revision("draft")
        mock_janitor.return_value.put_agent_md.return_value = {"ok": True}

        res = self.client.put(
            self._file_url(revision),
            {"path": "agent.md", "content": "# New body"},
            format="json",
        )

        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["id"], str(revision.id))
        mock_janitor.return_value.put_agent_md.assert_called_once_with(str(revision.id), "# New body")
        # agent.md is a bundle write — nothing published to the store.
        self.assertEqual(LLMSkill.objects.count(), 1)

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_put_skill_body_publishes_store_version_and_repins(self, mock_janitor: MagicMock) -> None:
        revision = self._revision("draft")

        res = self.client.put(
            self._file_url(revision),
            {"path": "skills/growth-review/SKILL.md", "content": "## Edited body"},
            format="json",
        )

        self.assertEqual(res.status_code, 200, res.content)
        latest = self._latest()
        self.assertEqual(latest.version, 2)
        self.assertEqual(latest.body, "## Edited body")
        # Body-only content carries the description forward.
        self.assertEqual(latest.description, "Original description")
        revision.refresh_from_db()
        self.assertEqual(
            revision.skill_refs,
            [
                {
                    "from_template": "growth-review",
                    "alias": "growth-review",
                    "version": 2,
                    "source_version_id": str(latest.id),
                }
            ],
        )
        # The draft bundle is never written for a skill edit — freeze
        # materializes the store version.
        mock_janitor.return_value.put_skill.assert_not_called()
        mock_janitor.return_value.put_agent_md.assert_not_called()

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_put_skill_resolves_alias_to_store_template(self, mock_janitor: MagicMock) -> None:
        revision = self._revision("draft", skill_refs=[{"from_template": "growth-review", "alias": "gr"}])

        res = self.client.put(
            self._file_url(revision),
            {"path": "skills/gr/SKILL.md", "content": "## Via alias"},
            format="json",
        )

        self.assertEqual(res.status_code, 200, res.content)
        latest = self._latest("growth-review")
        self.assertEqual(latest.version, 2)
        self.assertEqual(latest.body, "## Via alias")
        revision.refresh_from_db()
        self.assertEqual(revision.skill_refs[0]["alias"], "gr")
        self.assertEqual(revision.skill_refs[0]["version"], 2)
        self.assertEqual(revision.skill_refs[0]["source_version_id"], str(latest.id))

    def test_put_skill_frontmatter_updates_description(self) -> None:
        revision = self._revision("draft")
        content = "---\nname: growth-review\ndescription: New summary\n---\n## Edited\n"

        res = self.client.put(
            self._file_url(revision),
            {"path": "skills/growth-review/SKILL.md", "content": content},
            format="json",
        )

        self.assertEqual(res.status_code, 200, res.content)
        latest = self._latest()
        self.assertEqual(latest.description, "New summary")
        self.assertEqual(latest.body, "## Edited\n")

    def test_put_skill_invalid_frontmatter_returns_400(self) -> None:
        revision = self._revision("draft")
        content = "---\nname: [unclosed\n---\nbody"

        res = self.client.put(
            self._file_url(revision),
            {"path": "skills/growth-review/SKILL.md", "content": content},
            format="json",
        )

        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(LLMSkill.objects.count(), 1)

    @parameterized.expand(NON_DRAFT_STATES)
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_put_file_409_on_non_draft(self, state: str, mock_janitor: MagicMock) -> None:
        revision = self._revision(state)

        res = self.client.put(
            self._file_url(revision),
            {"path": "agent.md", "content": "blocked"},
            format="json",
        )

        self.assertEqual(res.status_code, 409, res.content)
        payload = res.json()
        self.assertEqual(payload["error"], "revision_not_draft")
        self.assertEqual(payload["state"], state)
        mock_janitor.return_value.put_agent_md.assert_not_called()
        self.assertEqual(LLMSkill.objects.count(), 1)

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_put_file_rejects_tool_source_path(self, mock_janitor: MagicMock) -> None:
        revision = self._revision("draft")

        res = self.client.put(
            self._file_url(revision),
            {"path": "tools/foo/source.ts", "content": "export default {}"},
            format="json",
        )

        self.assertEqual(res.status_code, 400, res.content)
        mock_janitor.return_value.put_agent_md.assert_not_called()
        self.assertEqual(LLMSkill.objects.count(), 1)

    def test_put_file_unreferenced_skill_returns_400(self) -> None:
        revision = self._revision("draft")

        res = self.client.put(
            self._file_url(revision),
            {"path": "skills/never-added/SKILL.md", "content": "## Body"},
            format="json",
        )

        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(LLMSkill.objects.count(), 1)

    def test_put_file_kernel_skill_is_code_locked(self) -> None:
        kernel_ids = sorted(all_kernel_skill_ids())
        if not kernel_ids:
            self.skipTest("no kernel skills shipped in this checkout")
        revision = self._revision("draft")

        res = self.client.put(
            self._file_url(revision),
            {"path": f"skills/{kernel_ids[0]}/SKILL.md", "content": "## Forged"},
            format="json",
        )

        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(LLMSkill.objects.count(), 1)

    def test_put_skill_denied_for_token_without_llm_skill_write(self) -> None:
        # A token with agents:write but no llm_skill:write must not be able to
        # rewrite a shared store skill through the agent authoring surface.
        client = self._bearer_client(["agents:read", "agents:write"])
        revision = self._revision("draft")

        res = client.put(
            self._file_url(revision),
            {"path": "skills/growth-review/SKILL.md", "content": "## Sneaky"},
            format="json",
        )

        self.assertEqual(res.status_code, 403, res.content)
        self.assertEqual(self._latest().version, 1)
        revision.refresh_from_db()
        self.assertNotIn("source_version_id", revision.skill_refs[0])

    def test_put_skill_allowed_for_token_with_llm_skill_write(self) -> None:
        client = self._bearer_client(["agents:read", "agents:write", "llm_skill:write"])
        revision = self._revision("draft")

        res = client.put(
            self._file_url(revision),
            {"path": "skills/growth-review/SKILL.md", "content": "## Scoped edit"},
            format="json",
        )

        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(self._latest().version, 2)

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_put_agent_md_needs_no_llm_skill_scope(self, mock_janitor: MagicMock) -> None:
        client = self._bearer_client(["agents:read", "agents:write"])
        revision = self._revision("draft")
        mock_janitor.return_value.put_agent_md.return_value = {"ok": True}

        res = client.put(
            self._file_url(revision),
            {"path": "agent.md", "content": "# Agents scope only"},
            format="json",
        )

        self.assertEqual(res.status_code, 200, res.content)

    # ── bulk import ────────────────────────────────────────────────────────

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_import_mixes_new_and_existing_skill(self, mock_janitor: MagicMock) -> None:
        revision = self._revision("draft")
        mock_janitor.return_value.put_agent_md.return_value = {"ok": True}

        res = self.client.post(
            self._import_url(revision),
            {
                "agent_md": "# Top-level",
                "skills": [
                    {"id": "growth-review", "body": "updated body"},
                    {"id": "fresh-skill", "description": "Brand new", "body": "## Hello"},
                ],
            },
            format="json",
        )

        self.assertEqual(res.status_code, 200, res.content)
        existing = self._latest("growth-review")
        self.assertEqual(existing.version, 2)
        self.assertEqual(existing.body, "updated body")
        # Existing skill preserves the store description; new skill takes the payload's.
        self.assertEqual(existing.description, "Original description")
        fresh = self._latest("fresh-skill")
        self.assertEqual(fresh.version, 1)
        self.assertEqual(fresh.description, "Brand new")
        self.assertEqual(fresh.body, "## Hello")
        revision.refresh_from_db()
        self.assertEqual(
            revision.skill_refs,
            [
                {
                    "from_template": "growth-review",
                    "alias": "growth-review",
                    "version": 2,
                    "source_version_id": str(existing.id),
                },
                {
                    "from_template": "fresh-skill",
                    "alias": "fresh-skill",
                    "version": 1,
                    "source_version_id": str(fresh.id),
                },
            ],
        )
        mock_janitor.return_value.put_agent_md.assert_called_once_with(str(revision.id), "# Top-level")
        mock_janitor.return_value.put_skill.assert_not_called()

    def test_import_attaches_unreferenced_store_skill_by_name(self) -> None:
        LLMSkill.objects.create(team=self.team, name="lonely-skill", description="Lonely", body="old")
        revision = self._revision("draft", skill_refs=[])

        # No description needed — the store skill already exists under this name.
        res = self.client.post(
            self._import_url(revision),
            {"skills": [{"id": "lonely-skill", "body": "new body"}]},
            format="json",
        )

        self.assertEqual(res.status_code, 200, res.content)
        latest = self._latest("lonely-skill")
        self.assertEqual(latest.version, 2)
        self.assertEqual(latest.body, "new body")
        revision.refresh_from_db()
        self.assertEqual(
            revision.skill_refs,
            [
                {
                    "from_template": "lonely-skill",
                    "alias": "lonely-skill",
                    "version": 2,
                    "source_version_id": str(latest.id),
                }
            ],
        )

    @parameterized.expand(NON_DRAFT_STATES)
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_import_409_on_non_draft(self, state: str, mock_janitor: MagicMock) -> None:
        revision = self._revision(state)

        res = self.client.post(
            self._import_url(revision),
            {"agent_md": "blocked", "skills": [{"id": "growth-review", "body": "blocked"}]},
            format="json",
        )

        self.assertEqual(res.status_code, 409, res.content)
        payload = res.json()
        self.assertEqual(payload["error"], "revision_not_draft")
        self.assertEqual(payload["state"], state)
        mock_janitor.return_value.put_agent_md.assert_not_called()
        self.assertEqual(LLMSkill.objects.count(), 1)

    @parameterized.expand(
        [
            ("spaces", "Has Spaces"),
            # `$` matches before a trailing newline, so `.match()` would accept
            # this and mint a store skill the janitor rejects at freeze —
            # `.fullmatch()` must reject it here.
            ("trailing_newline", "abc\n"),
        ]
    )
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_import_rejects_bad_skill_id_format(self, _name: str, bad_id: str, mock_janitor: MagicMock) -> None:
        revision = self._revision("draft")

        res = self.client.post(
            self._import_url(revision),
            {
                "agent_md": "# Never written",
                "skills": [{"id": bad_id, "description": "Bad", "body": "b"}],
            },
            format="json",
        )

        self.assertEqual(res.status_code, 400, res.content)
        # All-or-nothing: nothing published, nothing written to the bundle.
        mock_janitor.return_value.put_agent_md.assert_not_called()
        self.assertEqual(LLMSkill.objects.count(), 1)
        revision.refresh_from_db()
        self.assertNotIn("source_version_id", revision.skill_refs[0])

    def test_import_rejects_oversized_body(self) -> None:
        # The store caps bodies at 1 MB in its serializers only; this path calls
        # the services directly, so dropping the logic-layer guard would let a
        # 20 MB request body publish oversized versions the skills API refuses.
        # The valid first entry must NOT publish either — size is checked
        # up-front with the rest of the all-or-nothing validation.
        revision = self._revision("draft")

        res = self.client.post(
            self._import_url(revision),
            {
                "skills": [
                    {"id": "growth-review", "body": "fine"},
                    {"id": "big-one", "description": "Too big", "body": "a" * 1_000_001},
                ]
            },
            format="json",
        )

        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(self._latest().version, 1)
        self.assertFalse(LLMSkill.objects.filter(team=self.team, name="big-one").exists())

    def test_import_rejects_store_invalid_name_for_new_skill(self) -> None:
        # "my_skill" passes the janitor alias regex (underscores allowed) but
        # violates the store's name rules — creating it would mint a store row
        # the skills API itself refuses to create or address by name.
        revision = self._revision("draft")

        res = self.client.post(
            self._import_url(revision),
            {"skills": [{"id": "my_skill", "description": "New", "body": "b"}]},
            format="json",
        )

        self.assertEqual(res.status_code, 400, res.content)
        self.assertFalse(LLMSkill.objects.filter(team=self.team, name="my_skill").exists())

    def test_import_rejects_duplicate_ids(self) -> None:
        revision = self._revision("draft")

        res = self.client.post(
            self._import_url(revision),
            {
                "skills": [
                    {"id": "growth-review", "body": "one"},
                    {"id": "growth-review", "body": "two"},
                ]
            },
            format="json",
        )

        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(self._latest().version, 1)

    def test_import_new_skill_requires_description(self) -> None:
        revision = self._revision("draft")

        res = self.client.post(
            self._import_url(revision),
            {"skills": [{"id": "brand-new", "body": "## Hello"}]},
            format="json",
        )

        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(LLMSkill.objects.count(), 1)

    def test_import_rejects_kernel_skill_id(self) -> None:
        kernel_ids = sorted(all_kernel_skill_ids())
        if not kernel_ids:
            self.skipTest("no kernel skills shipped in this checkout")
        revision = self._revision("draft")

        res = self.client.post(
            self._import_url(revision),
            {"skills": [{"id": kernel_ids[0], "description": "Forged", "body": "b"}]},
            format="json",
        )

        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(LLMSkill.objects.count(), 1)

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_import_with_only_agent_md(self, mock_janitor: MagicMock) -> None:
        revision = self._revision("draft")
        mock_janitor.return_value.put_agent_md.return_value = {"ok": True}

        res = self.client.post(
            self._import_url(revision),
            {"agent_md": "# Only this"},
            format="json",
        )

        self.assertEqual(res.status_code, 200, res.content)
        mock_janitor.return_value.put_agent_md.assert_called_once_with(str(revision.id), "# Only this")
        self.assertEqual(LLMSkill.objects.count(), 1)
        revision.refresh_from_db()
        self.assertEqual(revision.skill_refs, [{"from_template": "growth-review", "alias": "growth-review"}])

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_import_with_empty_skills_array(self, mock_janitor: MagicMock) -> None:
        revision = self._revision("draft")

        res = self.client.post(self._import_url(revision), {"skills": []}, format="json")

        self.assertEqual(res.status_code, 200, res.content)
        mock_janitor.return_value.put_agent_md.assert_not_called()
        self.assertEqual(LLMSkill.objects.count(), 1)

    def test_import_rejects_exceeding_max_refs(self) -> None:
        refs = [{"from_template": "growth-review", "alias": f"alias-{i}"} for i in range(50)]
        revision = self._revision("draft", skill_refs=refs)

        res = self.client.post(
            self._import_url(revision),
            {"skills": [{"id": "one-more", "description": "Over the cap", "body": "b"}]},
            format="json",
        )

        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(LLMSkill.objects.count(), 1)

    def test_import_denied_for_token_without_llm_skill_write(self) -> None:
        client = self._bearer_client(["agents:read", "agents:write"])
        revision = self._revision("draft")

        res = client.post(
            self._import_url(revision),
            {"skills": [{"id": "growth-review", "body": "sneaky"}]},
            format="json",
        )

        self.assertEqual(res.status_code, 403, res.content)
        self.assertEqual(self._latest().version, 1)

    def test_import_of_new_skill_denied_without_resource_level_editor_access(self) -> None:
        # A brand-new id means the import CREATES a shared store skill, so it
        # must honour the same resource-level gate as LLMSkillViewSet's create —
        # not slip past because there's no object to check yet.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        # llm_skill inherits its access-control resource from llm_analytics.
        AccessControl.objects.create(team=self.team, resource="llm_analytics", resource_id=None, access_level="viewer")
        revision = self._revision("draft")

        res = self.client.post(
            self._import_url(revision),
            {"skills": [{"id": "brand-new-skill", "description": "New", "body": "b"}]},
            format="json",
        )

        self.assertEqual(res.status_code, 403, res.content)
        self.assertFalse(LLMSkill.objects.filter(team=self.team, name="brand-new-skill").exists())
