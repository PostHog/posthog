from datetime import datetime

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.outputs import Generation, LLMResult

from ee.hogai.llm import MaxChatOpenAI


@patch.dict("os.environ", {"OPENAI_API_KEY": "test-api-key"})
class TestMaxChatOpenAI(NonAtomicBaseTest):
    def setUp(self):
        super().setUp()
        # Setup test data
        self.team.timezone = "America/New_York"
        self.team.name = "Test Project"
        self.team.organization.name = "Test Organization"
        self.user.first_name = "John"
        self.user.last_name = "Doe"
        self.user.email = "john@example.com"

    def test_initialization_and_context_variables(self):
        """Test initialization and context variable extraction."""
        llm = MaxChatOpenAI(user=self.user, team=self.team, max_retries=5)

        # Test initialization
        self.assertEqual(llm._user, self.user)
        self.assertEqual(llm._team, self.team)
        self.assertEqual(llm.max_retries, 5)

        # Test context variables
        with patch("datetime.datetime") as mock_datetime:
            mock_now = datetime(2024, 1, 15, 10, 30, 45)
            mock_datetime.now.return_value = mock_now

            variables = llm._get_project_org_user_variables()

            self.assertEqual(variables["project_name"], "Test Project")
            self.assertEqual(variables["project_timezone"], "America/New_York")
            self.assertEqual(variables["project_datetime"], "2024-01-15 10:30:45")
            self.assertEqual(variables["organization_name"], "Test Organization")
            self.assertEqual(variables["user_full_name"], "John Doe")
            self.assertEqual(variables["user_email"], "john@example.com")

    def test_message_enrichment_with_context(self):
        """Test that context is properly injected into messages."""
        llm = MaxChatOpenAI(user=self.user, team=self.team)

        # Test with system messages present
        messages_with_system = [[SystemMessage(content="System prompt"), HumanMessage(content="User query")]]

        variables = llm._get_project_org_user_variables()
        llm._enrich_messages(messages_with_system, variables)

        # Context should be inserted after system messages
        self.assertEqual(len(messages_with_system[0]), 3)
        self.assertIsInstance(messages_with_system[0][1], SystemMessage)  # Our context
        self.assertIn("Test Project", str(messages_with_system[0][1].content))

        # Test without system messages
        messages_no_system = [[HumanMessage(content="User query")]]
        llm._enrich_messages(messages_no_system, variables)

        # Context should be inserted at the beginning
        self.assertEqual(len(messages_no_system[0]), 2)
        self.assertIsInstance(messages_no_system[0][0], SystemMessage)  # Our context

    def test_responses_api_instruction_enrichment(self):
        """Test instruction enrichment for responses API mode."""
        llm = MaxChatOpenAI(user=self.user, team=self.team)

        # Test with no existing instructions
        llm.model_kwargs = {}
        variables = llm._get_project_org_user_variables()
        llm._enrich_responses_api_model_kwargs(variables)

        self.assertIn("instructions", llm.model_kwargs)
        self.assertIn("Test Project", llm.model_kwargs["instructions"])

        # Test with existing instructions
        llm.model_kwargs = {"instructions": "Existing instructions"}
        llm._enrich_responses_api_model_kwargs(variables)

        # Should prepend context to existing instructions
        self.assertIn("Test Project", llm.model_kwargs["instructions"])
        self.assertIn("Existing instructions", llm.model_kwargs["instructions"])
        self.assertTrue(llm.model_kwargs["instructions"].endswith("Existing instructions"))

    def test_generate_methods_with_different_modes(self):
        """Test both sync and async generate methods in different modes."""
        # Test responses API mode
        llm_responses = MaxChatOpenAI(user=self.user, team=self.team, use_responses_api=True)

        mock_result = LLMResult(generations=[[Generation(text="Response")]])
        with patch("langchain_openai.ChatOpenAI.generate", return_value=mock_result) as mock_generate:
            messages = [[HumanMessage(content="Test query")]]
            result = llm_responses.generate(messages)

            # Should have enriched instructions
            self.assertIn("instructions", llm_responses.model_kwargs)
            self.assertIn("Test Project", llm_responses.model_kwargs["instructions"])
            self.assertEqual(result, mock_result)

        # Test regular mode (without responses API)
        llm_regular = MaxChatOpenAI(user=self.user, team=self.team, use_responses_api=False)

        with patch("langchain_openai.ChatOpenAI.generate", return_value=mock_result) as mock_generate:
            messages = [[HumanMessage(content="Test query")]]
            result = llm_regular.generate(messages)

            # Should have enriched messages with context
            called_messages = mock_generate.call_args[0][0]
            self.assertEqual(len(called_messages[0]), 2)  # Original + context
            self.assertIsInstance(called_messages[0][0], SystemMessage)  # Context message

    async def test_async_generate_with_context(self):
        """Test async generation properly includes context."""
        llm = MaxChatOpenAI(user=self.user, team=self.team, use_responses_api=False)

        mock_result = LLMResult(generations=[[Generation(text="Response")]])
        with patch("langchain_openai.ChatOpenAI.agenerate", return_value=mock_result) as mock_agenerate:
            messages = [[HumanMessage(content="Test query")]]
            await llm.agenerate(messages)

            # Verify context was added
            called_messages = mock_agenerate.call_args[0][0]
            self.assertEqual(len(called_messages[0]), 2)
            self.assertIn("Test Project", str(called_messages[0][0].content))
