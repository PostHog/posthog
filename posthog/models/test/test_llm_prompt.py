from posthog.test.base import PostHogTestCase

from posthog.models.llm_prompt import LLMPrompt


class TestLLMPrompt(PostHogTestCase):
    def test_versioning_logic(self):
        # 1. Initial creation starts at version 1
        prompt = LLMPrompt.objects.create(team=self.team, name="test_p", prompt={"text": "v1"}, created_by=self.user)
        self.assertEqual(prompt.version, 1)

        # 2. Prompt content change increments version
        prompt.prompt = {"text": "v2"}
        prompt.save()
        prompt.refresh_from_db()
        self.assertEqual(prompt.version, 2)

        # 3. Metadata-only update doesn't increment version
        prompt.name = "new_name"
        prompt.save()
        prompt.refresh_from_db()
        self.assertEqual(prompt.version, 2)

        # 4. Saving without changes doesn't increment version
        prompt.save()
        prompt.refresh_from_db()
        self.assertEqual(prompt.version, 2)
