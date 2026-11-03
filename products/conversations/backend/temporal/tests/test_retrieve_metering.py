from posthog.test.base import BaseTest
from unittest.mock import patch

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.models import KnowledgeUsageKey, KnowledgeUsageRecord
from products.conversations.backend.temporal.ai_reply.activities.retrieve import _retrieve_sync
from products.conversations.backend.temporal.ai_reply.schemas import RetrieveInput

RETRIEVE_MODULE = "products.conversations.backend.temporal.ai_reply.activities.retrieve"


class TestSupportRetrieveMetering(BaseTest):
    def _query_count(self) -> int:
        return (
            KnowledgeUsageRecord.objects.unscoped()
            .filter(team_id=self.team.id, usage_key=KnowledgeUsageKey.QUERIES)
            .count()
        )

    def test_each_query_is_metered_once_per_activity_even_when_retried(self) -> None:
        input = RetrieveInput(team_id=self.team.id, queries=["refunds", "shipping"])

        with (
            patch(f"{RETRIEVE_MODULE}.rerank_chunks", return_value=[]),
            patch.object(logic, "generate_embedding", side_effect=RuntimeError("no embeddings")),
        ):
            _retrieve_sync(input, "workflow:run-1:activity-1")
            _retrieve_sync(input, "workflow:run-1:activity-1")
            assert self._query_count() == 2

            _retrieve_sync(input, "workflow:run-2:activity-1")
            assert self._query_count() == 4
