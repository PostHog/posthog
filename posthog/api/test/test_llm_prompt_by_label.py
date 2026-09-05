from posthog.api.services.llm_prompt import get_prompts_by_label_queryset, set_prompt_label
from posthog.test.base import APIBaseTest
from products.ai_observability.backend.models.llm_prompt import LLMPrompt


class TestLLMPromptByLabelQuerySet(APIBaseTest):
    def test_get_prompts_by_label_queryset_returns_matching_versions(self) -> None:
        p1_v1 = LLMPrompt.objects.create(
            team=self.team,
            name="prompt-alpha",
            prompt="Alpha content v1",
            version=1,
            is_latest=False,
            created_by=self.user,
        )
        LLMPrompt.objects.create(
            team=self.team,
            name="prompt-alpha",
            prompt="Alpha content v2",
            version=2,
            is_latest=True,
            created_by=self.user,
        )
        p2_v1 = LLMPrompt.objects.create(
            team=self.team,
            name="prompt-beta",
            prompt="Beta content v1",
            version=1,
            is_latest=True,
            created_by=self.user,
        )

        set_prompt_label(self.team, user=self.user, prompt_name="prompt-alpha", label_name="production", version=1)
        set_prompt_label(self.team, user=self.user, prompt_name="prompt-beta", label_name="staging", version=1)

        qs_prod = get_prompts_by_label_queryset(self.team, "production")
        results_prod = list(qs_prod)
        assert len(results_prod) == 1
        assert results_prod[0].id == p1_v1.id
        assert results_prod[0].version == 1

        qs_staging = get_prompts_by_label_queryset(self.team, "staging")
        results_staging = list(qs_staging)
        assert len(results_staging) == 1
        assert results_staging[0].id == p2_v1.id
        assert results_staging[0].version == 1

        qs_empty = get_prompts_by_label_queryset(self.team, "nonexistent")
        assert list(qs_empty) == []

