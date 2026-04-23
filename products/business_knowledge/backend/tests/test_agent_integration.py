"""
Unit-level test that the support agent's prompt builder injects the knowledge
block only when the team has ready sources, and does NOT inject it for teams
without sources. This covers the agent-integration contract without firing a
real LLM call.
"""

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import sync_to_async

from products.business_knowledge.backend.logic import create_text_source
from products.conversations.backend.ai.prompt_builder import SupportAgentPromptBuilder


class TestSupportAgentPromptBuilder(BaseTest):
    def _build(self) -> SupportAgentPromptBuilder:
        context_manager = MagicMock()
        context_manager.get_group_names = AsyncMock(return_value=[])
        builder = SupportAgentPromptBuilder(self.team, self.user, context_manager)
        return builder

    async def test_injects_knowledge_prompt_when_team_has_sources(self) -> None:
        await sync_to_async(create_text_source)(
            team_id=self.team.id, created_by_id=self.user.id, name="Product FAQ", text="hello"
        )
        builder = self._build()
        with (
            patch.object(builder, "_aget_core_memory_text", new_callable=AsyncMock, return_value=""),
            patch.object(builder, "_get_billing_prompt", new_callable=AsyncMock, return_value=""),
        ):
            messages = await builder.get_prompts(state=MagicMock(), config={})
        joined = "\n".join(str(m.content) for m in messages)
        assert "business_knowledge_chunks" in joined
        assert "UNTRUSTED" in joined
        assert "Product FAQ" in joined

    async def test_omits_knowledge_prompt_when_team_has_none(self) -> None:
        builder = self._build()
        with (
            patch.object(builder, "_aget_core_memory_text", new_callable=AsyncMock, return_value=""),
            patch.object(builder, "_get_billing_prompt", new_callable=AsyncMock, return_value=""),
        ):
            messages = await builder.get_prompts(state=MagicMock(), config={})
        joined = "\n".join(str(m.content) for m in messages)
        assert "business_knowledge_chunks" not in joined
