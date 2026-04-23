"""
Deterministic retrieval evaluation for Stage 1.

No live LLM calls — we drive the exact ILIKE-based search recipe we teach the
agent and assert it finds the right chunk. Live-LLM agent runs are scheduled
nightly outside CI (see plan, "Retrieval eval" section).

Expected to grow: add every real support ticket where the agent failed to
retrieve the right doc to `retrieval_eval_fixture.yaml`. When a scenario
regresses, the fix is usually either a smarter chunker (tune target size,
add heading-aware splits) or — once the fixture recall drops below 0.7 — a
retrieval upgrade (FTS → pgvector), per the plan's escalation trigger.
"""

from pathlib import Path

from posthog.test.base import BaseTest

import yaml
from parameterized import parameterized

from products.business_knowledge.backend.logic import create_text_source
from products.business_knowledge.backend.models import KnowledgeChunk

FIXTURE_PATH = Path(__file__).parent / "retrieval_eval_fixture.yaml"


def _load_scenarios():
    with FIXTURE_PATH.open("r") as f:
        data = yaml.safe_load(f)
    return [(s["id"], s) for s in data["scenarios"]]


class TestRetrievalEval(BaseTest):
    @parameterized.expand(_load_scenarios())
    def test_scenario_retrieves_expected_chunk(self, _id: str, scenario: dict) -> None:
        create_text_source(
            team_id=self.team.id,
            created_by_id=self.user.id,
            name=scenario["source_name"],
            text=scenario["text"],
        )

        # Mirror the agent's search recipe: OR across keywords via ILIKE on
        # chunk content, ordered by length desc. If the fixture grows to the
        # point where this exact recipe misses >30% of scenarios, that's the
        # escalation trigger to bring in FTS / pgvector.
        from django.db.models import Q

        q = Q()
        for kw in scenario["keywords"]:
            q |= Q(content__icontains=kw)
        chunks = KnowledgeChunk.objects.filter(team_id=self.team.id).filter(q).order_by("-char_count")[:5]
        expected = scenario["expected_substring"]
        matched = any(expected.lower() in c.content.lower() for c in chunks)
        assert matched, (
            f"Scenario {scenario['id']} did not retrieve a chunk containing '{expected}'. "
            f"Retrieved: {[c.content[:80] for c in chunks]}"
        )
