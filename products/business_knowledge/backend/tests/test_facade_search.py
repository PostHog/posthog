from posthog.test.base import BaseTest

from posthog.models.scoping import team_scope

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.facade import api as business_knowledge_facade
from products.business_knowledge.backend.facade.contracts import KnowledgeHit
from products.business_knowledge.backend.models import KnowledgeDocument, SafetyVerdict


class TestFacadeSearch(BaseTest):
    def test_search_knowledge_returns_the_matching_page_as_a_hit(self) -> None:
        source = logic.create_text_source(
            team_id=self.team.id,
            created_by_id=self.user.id,
            name="docs",
            text="Feature flags can roll out to a percentage of users.",
        )
        page = "https://posthog.com/docs/feature-flags/rollouts"
        with team_scope(self.team.id, canonical=True):
            KnowledgeDocument.objects.filter(source_id=source.id).update(safety_verdict=SafetyVerdict.SAFE, url=page)

        hits = business_knowledge_facade.search_knowledge(team_id=self.team.id, query="feature flags rollout")

        assert hits
        assert isinstance(hits[0], KnowledgeHit)
        assert hits[0].url == page
