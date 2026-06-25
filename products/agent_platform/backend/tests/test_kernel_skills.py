from __future__ import annotations

from django.test import SimpleTestCase

from parameterized import parameterized

from ..logic.kernel_skills import KernelSkill, _all_kernel_skills, kernel_skills_for


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
