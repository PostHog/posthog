from __future__ import annotations

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework.test import APIClient

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.skills.backend.models.skills import LLMSkill, LLMSkillFile

from ..models import AgentApplication, AgentRevision


def _freeze_result(skills: list[dict] | None = None) -> dict:
    """A janitor freeze response. `skills` are the bundle-derived skills — the
    janitor tags each `source: 'bundle'` (store refs are NOT here; Django appends
    them). Mirror that here so the mock matches the real contract."""
    bundle_skills = [{"source": "bundle", **s} for s in (skills or [])]
    return {
        "bundle_sha256": "a" * 64,
        "derived_spec": {"model": "x", "triggers": [], "skills": bundle_skills, "tools": []},
    }


class TestFreezeResolvesSkillRefs(APIBaseTest):
    databases = {
        "default",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def setUp(self) -> None:
        super().setUp()
        self.skill = LLMSkill.objects.create(
            team=self.team,
            name="triage-helper",
            description="Decide which inbound tickets need a human.",
            body="The triage body.",
        )
        LLMSkillFile.objects.create(skill=self.skill, path="references/api.md", content="# API")
        self.application = AgentApplication.all_teams.create(
            team_id=self.team.id, slug="freeze-agent", name="Freeze agent", description=""
        )
        self.revision = AgentRevision.all_teams.create(
            application=self.application,
            spec={"model": "x", "triggers": []},
            skill_refs=[{"from_template": "triage-helper", "alias": "triage"}],
            state="draft",
            bundle_uri="fs://test/",
        )
        self.url = (
            f"/api/projects/{self.team.id}/agent_applications/{self.application.id}"
            f"/revisions/{self.revision.id}/freeze/"
        )

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_appends_store_ref_as_live_source_not_baked(self, mock_janitor: MagicMock) -> None:
        # A latest-tracking store ref is resolved (to validate + snapshot its
        # description) but NEVER baked into the bundle — it's appended to the spec
        # as a `source: 'store'` entry the runtime resolves live, unpinned.
        client = mock_janitor.return_value
        client.freeze.return_value = _freeze_result(skills=[])

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 200, res.content)

        client.put_skill.assert_not_called()  # store skills are not materialized
        client.freeze.assert_called_once_with(str(self.revision.id))
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.state, "ready")
        skill = self.revision.spec["skills"][0]
        self.assertEqual(skill["id"], "triage")
        self.assertEqual(skill["source"], "store")
        self.assertEqual(skill["from_template"], "triage-helper")
        self.assertEqual(skill["description"], "Decide which inbound tickets need a human.")
        # Latest-tracking: no pinned version / anchor.
        self.assertNotIn("version", skill)
        self.assertNotIn("source_version_id", skill)
        # ...and the writeback leaves the ref unpinned so it keeps tracking latest.
        self.assertNotIn("version", self.revision.skill_refs[0])

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_pins_authored_pinned_ref(self, mock_janitor: MagicMock) -> None:
        # An author who pinned a version gets the immutable anchor stamped (so a
        # fork can't drift), on both the spec entry and the skill_refs writeback.
        self.revision.skill_refs = [{"from_template": "triage-helper", "alias": "triage", "version": 1}]
        self.revision.save(update_fields=["skill_refs"])
        client = mock_janitor.return_value
        client.freeze.return_value = _freeze_result(skills=[])

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 200, res.content)
        self.revision.refresh_from_db()
        skill = self.revision.spec["skills"][0]
        self.assertEqual(skill["source"], "store")
        self.assertEqual(skill["version"], 1)
        self.assertEqual(skill["source_version_id"], str(self.skill.id))
        pinned = self.revision.skill_refs[0]
        self.assertEqual(pinned["version"], 1)
        self.assertEqual(pinned["source_version_id"], str(self.skill.id))

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_tags_bundle_derived_skills_source_bundle(self, mock_janitor: MagicMock) -> None:
        # Skills the janitor derived from the bundle's folders are tagged
        # `source: 'bundle'`; they coexist with appended store refs.
        client = mock_janitor.return_value
        client.freeze.return_value = _freeze_result(
            skills=[{"id": "inline-helper", "path": "skills/inline-helper/SKILL.md", "description": "d"}]
        )

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 200, res.content)
        self.revision.refresh_from_db()
        by_id = {s["id"]: s for s in self.revision.spec["skills"]}
        self.assertEqual(by_id["inline-helper"]["source"], "bundle")
        self.assertEqual(by_id["inline-helper"]["path"], "skills/inline-helper/SKILL.md")
        self.assertEqual(by_id["triage"]["source"], "store")

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_rejects_store_alias_colliding_with_bundle_skill_id(self, mock_janitor: MagicMock) -> None:
        # A store ref alias that collides with a bundled skill id is ambiguous —
        # both would be `skills[].id == 'triage'`. Refuse, leave the row a draft.
        client = mock_janitor.return_value
        client.freeze.return_value = _freeze_result(
            skills=[{"id": "triage", "path": "skills/triage/SKILL.md", "description": "d"}]
        )

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("collide", str(res.content))
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.state, "draft")

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_fails_loud_on_missing_skill(self, mock_janitor: MagicMock) -> None:
        self.revision.skill_refs = [{"from_template": "ghost", "alias": "g"}]
        self.revision.save(update_fields=["skill_refs"])

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 400, res.content)
        mock_janitor.return_value.freeze.assert_not_called()
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.state, "draft")

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_rejects_more_than_max_skill_refs(self, mock_janitor: MagicMock) -> None:
        # The serializer caps refs at 50, but fork / raw write can smuggle more into
        # the column — freeze must re-bound the count before fanning out.
        self.revision.skill_refs = [{"from_template": "triage-helper", "alias": f"a{i}"} for i in range(51)]
        self.revision.save(update_fields=["skill_refs"])

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 400, res.content)
        mock_janitor.return_value.freeze.assert_not_called()
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.state, "draft")

    @property
    def _detail_url(self) -> str:
        return f"/api/projects/{self.team.id}/agent_applications/{self.application.id}/revisions/{self.revision.id}/"

    def test_spec_write_strips_author_skills(self) -> None:
        # skills[] is server-derived at freeze. Editing an unrelated spec field must
        # NOT 400, and an author-supplied skills[] is dropped (pinned to the server
        # value, empty here) — authors write skill FILES, not spec entries.
        res = self.client.patch(
            self._detail_url,
            {
                "spec": {
                    "models": {"mode": "manual", "models": [{"model": "faux/new"}]},
                    "triggers": [],
                    "skills": [{"id": "evil", "path": "skills/evil/SKILL.md", "source": "bundle"}],
                }
            },
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.spec["models"]["models"][0]["model"], "faux/new")
        self.assertEqual(self.revision.spec.get("skills", []), [])

    @property
    def _skill_refs_url(self) -> str:
        return (
            f"/api/projects/{self.team.id}/agent_applications/{self.application.id}"
            f"/revisions/{self.revision.id}/skill_refs/"
        )

    def test_set_skill_refs_replaces_the_list(self) -> None:
        res = self.client.put(
            self._skill_refs_url,
            {
                "skill_refs": [
                    {"from_template": "triage-helper", "alias": "a"},
                    {"from_template": "triage-helper", "alias": "b", "version": 2},
                ]
            },
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.revision.refresh_from_db()
        self.assertEqual([r["alias"] for r in self.revision.skill_refs], ["a", "b"])
        self.assertEqual(self.revision.skill_refs[1]["version"], 2)

    def test_set_skill_refs_rejects_duplicate_alias(self) -> None:
        res = self.client.put(
            self._skill_refs_url,
            {"skill_refs": [{"from_template": "x", "alias": "dup"}, {"from_template": "y", "alias": "dup"}]},
            format="json",
        )
        self.assertEqual(res.status_code, 400, res.content)

    def test_set_skill_refs_blocked_on_non_draft(self) -> None:
        self.revision.state = "ready"
        self.revision.save(update_fields=["state"])
        res = self.client.put(
            self._skill_refs_url,
            {"skill_refs": [{"from_template": "triage-helper", "alias": "a"}]},
            format="json",
        )
        self.assertEqual(res.status_code, 400, res.content)

    def _bearer_client(self, scopes: list[str]) -> APIClient:
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="agent-key", user=self.user, secure_value=hash_key_value(raw), scopes=scopes
        )
        client = APIClient()  # no session — only the Bearer token authenticates
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        return client

    def test_freeze_denied_for_token_without_llm_skill_read(self) -> None:
        # A token with agents:write but no llm_skill:read must not be able to read
        # store-skill content via the bundle/spec it attaches at freeze.
        client = self._bearer_client(["agents:read", "agents:write"])
        res = client.post(self.url)
        self.assertEqual(res.status_code, 403, res.content)
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.state, "draft")

    def test_set_skill_refs_denied_for_token_without_llm_skill_read(self) -> None:
        client = self._bearer_client(["agents:read", "agents:write"])
        res = client.put(
            self._skill_refs_url,
            {"skill_refs": [{"from_template": "triage-helper", "alias": "a"}]},
            format="json",
        )
        self.assertEqual(res.status_code, 403, res.content)

    def test_set_skill_refs_allowed_for_token_with_llm_skill_read(self) -> None:
        client = self._bearer_client(["agents:read", "agents:write", "llm_skill:read"])
        res = client.put(
            self._skill_refs_url,
            {"skill_refs": [{"from_template": "triage-helper", "alias": "a"}]},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.revision.refresh_from_db()
        self.assertEqual([r["alias"] for r in self.revision.skill_refs], ["a"])
