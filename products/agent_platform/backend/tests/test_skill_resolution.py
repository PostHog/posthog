from posthog.test.base import BaseTest

from rest_framework.exceptions import ValidationError

from products.agent_platform.backend.logic.skill_resolution import resolve_skill_ref, stamp_skill_provenance
from products.skills.backend.models.skills import LLMSkill, LLMSkillFile


class TestResolveSkillRef(BaseTest):
    def _make_skill(self, name="triage-helper", version=1, is_latest=True, body="Body text here.", files=None):
        skill = LLMSkill.objects.create(
            team=self.team,
            name=name,
            description="Decide which inbound tickets need a human.",
            body=body,
            version=version,
            is_latest=is_latest,
        )
        for path, content in (files or {}).items():
            LLMSkillFile.objects.create(skill=skill, path=path, content=content)
        return skill

    def test_resolves_latest_with_rendered_frontmatter_and_companions(self):
        skill = self._make_skill(files={"references/api.md": "# API\nsee here"})

        resolved = resolve_skill_ref(self.team, {"from_template": "triage-helper", "alias": "triage"})

        self.assertEqual(resolved.alias, "triage")
        # body is the *rendered* SKILL.md so the janitor reads the frontmatter
        # description, not the first prose line.
        self.assertIn("name: triage-helper", resolved.body)
        self.assertIn("Decide which inbound tickets need a human.", resolved.body)
        self.assertIn("Body text here.", resolved.body)
        self.assertEqual(resolved.files, [{"path": "references/api.md", "content": "# API\nsee here"}])
        self.assertEqual(resolved.version, 1)
        self.assertEqual(resolved.source_version_id, str(skill.id))

    def test_pins_specific_version_not_latest(self):
        self._make_skill(name="pinned", version=1, is_latest=False, body="v1 body")
        self._make_skill(name="pinned", version=2, is_latest=True, body="v2 body")

        resolved = resolve_skill_ref(self.team, {"from_template": "pinned", "alias": "p", "version": 1})

        self.assertEqual(resolved.version, 1)
        self.assertIn("v1 body", resolved.body)

    def test_source_version_id_pin_resolves_even_when_archived(self):
        # A pinned version stays the immortal anchor: archiving the skill (soft-delete)
        # must not break a fork's re-freeze against the exact version it shipped.
        skill = self._make_skill(name="archived-skill", body="pinned body")
        skill_id = str(skill.id)
        LLMSkill.objects.filter(id=skill.id).update(deleted=True)

        resolved = resolve_skill_ref(
            self.team,
            {"from_template": "archived-skill", "alias": "a", "source_version_id": skill_id},
        )
        self.assertEqual(resolved.source_version_id, skill_id)
        self.assertIn("pinned body", resolved.body)

    def test_archived_skill_without_pin_fails_loud(self):
        # Without a source_version_id pin, an archived skill is gone (resolves latest).
        skill = self._make_skill(name="gone", body="x")
        LLMSkill.objects.filter(id=skill.id).update(deleted=True)
        with self.assertRaises(ValidationError):
            resolve_skill_ref(self.team, {"from_template": "gone", "alias": "g"})

    def test_missing_skill_fails_loud(self):
        with self.assertRaises(ValidationError):
            resolve_skill_ref(self.team, {"from_template": "does-not-exist", "alias": "x"})

    def test_malformed_ref_fails_loud(self):
        with self.assertRaises(ValidationError):
            resolve_skill_ref(self.team, {"alias": "x"})

    def test_stamp_provenance_matches_by_alias(self):
        derived_spec = {"skills": [{"id": "triage", "path": "skills/triage/SKILL.md", "description": "d"}]}
        stamp_skill_provenance(
            derived_spec,
            {"triage": {"from_template": "triage-helper", "version": 3, "source_version_id": "abc"}},
        )
        skill = derived_spec["skills"][0]
        self.assertEqual(skill["from_template"], "triage-helper")
        self.assertEqual(skill["version"], 3)
        self.assertEqual(skill["source_version_id"], "abc")
