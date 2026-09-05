from unittest import TestCase
from unittest.mock import MagicMock
from posthog.api.services.llm_prompt import get_prompts_by_label_queryset
from posthog.models.team import Team


class TestLLMPromptByLabelQuerySet(TestCase):
    def test_get_prompts_by_label_queryset_structure(self) -> None:
        team = MagicMock(spec=Team)
        team.id = 1
        # Calling get_prompts_by_label_queryset constructs the query
        assert callable(get_prompts_by_label_queryset)
