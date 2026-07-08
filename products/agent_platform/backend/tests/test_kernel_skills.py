from __future__ import annotations

import tempfile
from pathlib import Path

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from ..logic import kernel_skills as ks
from ..logic.kernel_skills import KernelSkill, _all_kernel_skills, kernel_skills_for


def _good_md(description: str = "A one-line description.", agents: str = "agent-x") -> str:
    return f"---\nname: s\ndescription: {description}\nagents:\n- {agents}\n---\n\n# Body\n"


class TestKernelSkillRegistry(SimpleTestCase):
    def test_real_folder_loads_and_maps_to_designated_agent(self) -> None:
        ids = {k.id for k in kernel_skills_for("agent-builder")}
        self.assertIn("safety-and-boundaries", ids)
        # An agent the platform hasn't designated receives none of them.
        self.assertEqual(kernel_skills_for("some-random-user-agent"), [])

    def test_every_kernel_skill_is_well_formed(self) -> None:
        skills = _all_kernel_skills()
        self.assertTrue(skills)
        for k in skills:
            self.assertTrue(k.description, k.id)
            self.assertTrue(k.agents, k.id)
            # body keeps frontmatter so the freeze-time derivation reads the same
            # description the index reports.
            self.assertTrue(k.body.startswith("---\n"), k.id)
            # The janitor derives spec.skills[].description from only the first
            # physical `description:` line, capped at 280 — a folded/over-long
            # description would silently truncate the model's load signal. The
            # loader enforces parity; assert the shipped files honour it.
            self.assertNotIn("\n", k.description, k.id)
            self.assertLessEqual(len(k.description), 280, k.id)

    @parameterized.expand(
        [
            ("wildcard matches anything", frozenset({"*"}), "any-slug", True),
            ("slug in set matches", frozenset({"a", "b"}), "a", True),
            ("slug not in set misses", frozenset({"a", "b"}), "c", False),
            ("wildcard beats specific", frozenset({"*", "a"}), "z", True),
        ]
    )
    def test_applies_to(self, _name: str, agents: frozenset[str], slug: str, expected: bool) -> None:
        skill = KernelSkill(id="x", description="d", body="b", agents=agents)
        self.assertEqual(skill.applies_to(slug), expected)


class TestKernelSkillLoader(SimpleTestCase):
    @staticmethod
    def _folder(root: str, name: str, content: str | None) -> Path:
        d = Path(root) / name
        d.mkdir()
        if content is not None:
            (d / "SKILL.md").write_text(content)
        return d

    @parameterized.expand(
        [
            ("missing SKILL.md", "ok-id", None),
            ("invalid folder id", "Bad-Caps", _good_md()),
            ("no frontmatter", "ok-id", "# just a body, no fences\n"),
            # LF fences but a CR inside the block — the janitor's single-line
            # derivation and Python's YAML parse would disagree silently.
            ("CR in frontmatter", "ok-id", "---\nname: s\ndescription: x\r\nagents:\n- agent-x\n---\n\nbody"),
            ("empty description", "ok-id", "---\nname: s\ndescription:\nagents:\n- agent-x\n---\n\nbody"),
            # Folded multi-line description: YAML reads the whole thing, the
            # janitor reads only the first line → parity guard must reject it.
            ("folded description", "ok-id", "---\nname: s\ndescription: one\n  two\nagents:\n- agent-x\n---\n\nbody"),
            ("missing agents", "ok-id", "---\nname: s\ndescription: x\n---\n\nbody"),
            ("invalid agent slug", "ok-id", _good_md(agents="Bad-Slug")),
            (
                "wildcard mixed with slug",
                "ok-id",
                "---\nname: s\ndescription: x\nagents:\n- '*'\n- agent-x\n---\n\nbody",
            ),
        ]
    )
    def test_load_skill_rejects(self, _name: str, folder_name: str, content: str | None) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                ks._load_skill(self._folder(tmp, folder_name, content))

    def test_load_skill_accepts_well_formed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = ks._load_skill(self._folder(tmp, "ok-id", _good_md(agents="agent-x")))
            self.assertEqual(skill.id, "ok-id")
            self.assertEqual(skill.agents, frozenset({"agent-x"}))

    def test_runtime_scoping_survives_unrelated_bad_folders(self) -> None:
        # A malformed folder targeting a DIFFERENT agent, plus a cruft dir, must
        # not break freeze for the agent we're loading — runtime only validates
        # folders that target the slug. The strict whole-set loader still rejects
        # the shipped set, so the malformation is caught in CI.
        with tempfile.TemporaryDirectory() as tmp:
            self._folder(tmp, "good", _good_md(agents="agent-x"))
            self._folder(tmp, "__pycache__", "garbage")  # cruft: skipped, not a skill
            self._folder(tmp, "broken", "---\nname: s\ndescription: x\n---\n\nbody")  # no agents
            with patch.object(ks, "_KERNEL_SKILLS_DIR", Path(tmp)):
                self.assertEqual([k.id for k in ks.kernel_skills_for("agent-x")], ["good"])
                with self.assertRaises(ValueError):
                    _all_kernel_skills()
