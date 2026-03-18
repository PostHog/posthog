from datetime import datetime

from posthog.test.base import BaseTest
from unittest.mock import patch

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, Generation, LLMResult
from parameterized import parameterized

from ee.hogai.llm import BILLING_SKIPPED_COUNTER, MaxChatAnthropic, MaxChatOpenAI


@patch.dict("os.environ", {"OPENAI_API_KEY": "test-api-key", "ANTHROPIC_API_KEY": "test-api-key"})
class TestMaxChatOpenAI(BaseTest):
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
        with patch("datetime.datetime") as mock_datetime:
            for llm in (
                MaxChatOpenAI(user=self.user, team=self.team),
                MaxChatAnthropic(user=self.user, team=self.team, model="claude"),
            ):
                # Test initialization
                self.assertEqual(llm.user, self.user)
                self.assertEqual(llm.team, self.team)
                self.assertIsNotNone(llm.max_retries)

                # Test context variables
                mock_now = datetime(2024, 1, 15, 10, 30, 45)
                mock_datetime.now.return_value = mock_now

                variables = llm._get_project_org_user_variables()

                self.assertEqual(variables["project_name"], "Test Project")
                self.assertEqual(variables["project_timezone"], "America/New_York")
                self.assertEqual(variables["project_datetime"], "2024-01-15 05:30:45")
                self.assertEqual(variables["organization_name"], "Test Organization")
                self.assertEqual(variables["user_full_name"], "John Doe")
                self.assertEqual(variables["user_email"], "john@example.com")

    def test_message_enrichment_with_context(self):
        """Test that context is properly injected into messages."""
        for llm in (
            MaxChatOpenAI(user=self.user, team=self.team),
            MaxChatAnthropic(user=self.user, team=self.team, model="claude"),
        ):
            # Test with system messages present
            messages_with_system = [[SystemMessage(content="System prompt"), HumanMessage(content="User query")]]

            variables = llm._get_project_org_user_variables()
            messages_with_system = llm._enrich_messages(messages_with_system, variables)

            # Context should be inserted after system messages
            self.assertEqual(len(messages_with_system[0]), 3)
            self.assertIsInstance(messages_with_system[0][1], SystemMessage)  # Our context
            self.assertIn("Test Project", str(messages_with_system[0][1].content))

            # Test without system messages
            messages_no_system: list[list[BaseMessage]] = [[HumanMessage(content="User query")]]
            messages_no_system = llm._enrich_messages(messages_no_system, variables)

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

    def test_openai_generate_methods_with_different_modes(self):
        """Test both sync and async generate methods in different modes."""
        # Test responses API mode
        llm_responses = MaxChatOpenAI(user=self.user, team=self.team, use_responses_api=True)

        mock_result = LLMResult(generations=[[Generation(text="Response")]])
        with patch("langchain_openai.ChatOpenAI.generate", return_value=mock_result) as mock_generate:
            messages: list[list[BaseMessage]] = [[HumanMessage(content="Test query")]]
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

    async def test_openai_async_generate_with_context(self):
        """Test async generation properly includes context."""
        llm = MaxChatOpenAI(user=self.user, team=self.team, use_responses_api=False)

        mock_result = LLMResult(generations=[[Generation(text="Response")]])
        with patch("langchain_openai.ChatOpenAI.agenerate", return_value=mock_result) as mock_agenerate:
            messages: list[list[BaseMessage]] = [[HumanMessage(content="Test query")]]
            await llm.agenerate(messages)

            # Verify context was added
            called_messages = mock_agenerate.call_args[0][0]
            self.assertEqual(len(called_messages[0]), 2)
            self.assertIn("Test Project", str(called_messages[0][0].content))

    async def test_anthropic_async_generate_with_context(self):
        """Test async generation properly includes context."""
        llm = MaxChatAnthropic(user=self.user, team=self.team, model="claude")

        mock_result = LLMResult(generations=[[Generation(text="Response")]])
        with patch("langchain_anthropic.ChatAnthropic.agenerate", return_value=mock_result) as mock_agenerate:
            messages: list[list[BaseMessage]] = [[HumanMessage(content="Test query")]]
            await llm.agenerate(messages)

            # Verify context was added
            called_messages = mock_agenerate.call_args[0][0]
            self.assertEqual(len(called_messages[0]), 2)
            self.assertIn("Test Project", str(called_messages[0][0].content))

    def test_invoke_with_context(self):
        """Test invoke method properly includes context."""
        llm = MaxChatOpenAI(user=self.user, team=self.team, use_responses_api=False)

        mock_result = LLMResult(generations=[[ChatGeneration(message=AIMessage(content="Response"))]])
        with patch("langchain_openai.ChatOpenAI.generate", return_value=mock_result) as mock_generate:
            messages = [HumanMessage(content="Test query")]
            llm.invoke(messages)

            called_messages = mock_generate.call_args[0][0]
            self.assertEqual(len(called_messages[0]), 2)
            self.assertIn("Test Project", str(called_messages[0][0].content))

        anthropic_llm = MaxChatAnthropic(user=self.user, team=self.team, model="claude")

        with patch("langchain_anthropic.ChatAnthropic.generate", return_value=mock_result) as mock_generate:
            messages = [HumanMessage(content="Test query")]
            anthropic_llm.invoke(messages)

            called_messages = mock_generate.call_args[0][0]
            self.assertEqual(len(called_messages[0]), 2)
            self.assertIn("Test Project", str(called_messages[0][0].content))

    async def test_ainvoke_with_context(self):
        """Test ainvoke method properly includes context."""
        llm = MaxChatOpenAI(user=self.user, team=self.team, use_responses_api=False)

        mock_result = LLMResult(generations=[[ChatGeneration(message=AIMessage(content="Response"))]])
        with patch("langchain_openai.ChatOpenAI.agenerate", return_value=mock_result) as mock_agenerate:
            messages = [HumanMessage(content="Test query")]
            await llm.ainvoke(messages)

            called_messages = mock_agenerate.call_args[0][0]
            self.assertEqual(len(called_messages[0]), 2)
            self.assertIn("Test Project", str(called_messages[0][0].content))

        anthropic_llm = MaxChatAnthropic(user=self.user, team=self.team, model="claude")

        with patch("langchain_anthropic.ChatAnthropic.agenerate", return_value=mock_result) as mock_agenerate:
            messages = [HumanMessage(content="Test query")]
            await anthropic_llm.ainvoke(messages)

            called_messages = mock_agenerate.call_args[0][0]
            self.assertEqual(len(called_messages[0]), 2)
            self.assertIn("Test Project", str(called_messages[0][0].content))

    def test_billable_false_by_default(self):
        """Test that billable defaults to False."""
        llm_openai = MaxChatOpenAI(user=self.user, team=self.team)
        llm_anthropic = MaxChatAnthropic(user=self.user, team=self.team, model="claude")

        self.assertEqual(llm_openai.billable, False)
        self.assertEqual(llm_anthropic.billable, False)

    def test_billable_metadata_when_false(self):
        """Test that $ai_billable metadata is False when billable=False."""
        llm = MaxChatOpenAI(user=self.user, team=self.team, use_responses_api=False, billable=False)

        mock_result = LLMResult(generations=[[Generation(text="Response")]])
        with patch("langchain_openai.ChatOpenAI.generate", return_value=mock_result) as mock_generate:
            messages: list[list[BaseMessage]] = [[HumanMessage(content="Test query")]]
            llm.generate(messages)

            call_kwargs = mock_generate.call_args.kwargs
            self.assertIn("metadata", call_kwargs)
            self.assertIn("posthog_properties", call_kwargs["metadata"])
            self.assertEqual(call_kwargs["metadata"]["posthog_properties"]["$ai_billable"], False)
            self.assertEqual(call_kwargs["metadata"]["posthog_properties"]["team_id"], self.team.id)

    def test_billable_metadata_when_true(self):
        """Test that $ai_billable metadata is True when billable=True."""
        llm = MaxChatOpenAI(user=self.user, team=self.team, use_responses_api=False, billable=True)

        mock_result = LLMResult(generations=[[Generation(text="Response")]])
        with patch("langchain_openai.ChatOpenAI.generate", return_value=mock_result) as mock_generate:
            messages: list[list[BaseMessage]] = [[HumanMessage(content="Test query")]]
            llm.generate(messages)

            call_kwargs = mock_generate.call_args.kwargs
            self.assertIn("metadata", call_kwargs)
            self.assertIn("posthog_properties", call_kwargs["metadata"])
            self.assertEqual(call_kwargs["metadata"]["posthog_properties"]["$ai_billable"], True)
            self.assertEqual(call_kwargs["metadata"]["posthog_properties"]["team_id"], self.team.id)

    async def test_billable_metadata_async_when_false(self):
        """Test that $ai_billable metadata is False in async generate when billable=False."""
        llm = MaxChatOpenAI(user=self.user, team=self.team, use_responses_api=False, billable=False)

        mock_result = LLMResult(generations=[[Generation(text="Response")]])
        with patch("langchain_openai.ChatOpenAI.agenerate", return_value=mock_result) as mock_agenerate:
            messages: list[list[BaseMessage]] = [[HumanMessage(content="Test query")]]
            await llm.agenerate(messages)

            call_kwargs = mock_agenerate.call_args.kwargs
            self.assertIn("metadata", call_kwargs)
            self.assertIn("posthog_properties", call_kwargs["metadata"])
            self.assertEqual(call_kwargs["metadata"]["posthog_properties"]["$ai_billable"], False)
            self.assertEqual(call_kwargs["metadata"]["posthog_properties"]["team_id"], self.team.id)

    async def test_billable_metadata_async_when_true(self):
        """Test that $ai_billable metadata is True in async generate when billable=True."""
        llm = MaxChatOpenAI(user=self.user, team=self.team, use_responses_api=False, billable=True)

        mock_result = LLMResult(generations=[[Generation(text="Response")]])
        with patch("langchain_openai.ChatOpenAI.agenerate", return_value=mock_result) as mock_agenerate:
            messages: list[list[BaseMessage]] = [[HumanMessage(content="Test query")]]
            await llm.agenerate(messages)

            call_kwargs = mock_agenerate.call_args.kwargs
            self.assertIn("metadata", call_kwargs)
            self.assertIn("posthog_properties", call_kwargs["metadata"])
            self.assertEqual(call_kwargs["metadata"]["posthog_properties"]["$ai_billable"], True)
            self.assertEqual(call_kwargs["metadata"]["posthog_properties"]["team_id"], self.team.id)

    def test_billable_metadata_anthropic_when_false(self):
        """Test that $ai_billable metadata is False for Anthropic when billable=False."""
        llm = MaxChatAnthropic(user=self.user, team=self.team, model="claude", billable=False)

        mock_result = LLMResult(generations=[[Generation(text="Response")]])
        with patch("langchain_anthropic.ChatAnthropic.generate", return_value=mock_result) as mock_generate:
            messages: list[list[BaseMessage]] = [[HumanMessage(content="Test query")]]
            llm.generate(messages)

            call_kwargs = mock_generate.call_args.kwargs
            self.assertIn("metadata", call_kwargs)
            self.assertIn("posthog_properties", call_kwargs["metadata"])
            self.assertEqual(call_kwargs["metadata"]["posthog_properties"]["$ai_billable"], False)
            self.assertEqual(call_kwargs["metadata"]["posthog_properties"]["team_id"], self.team.id)

    def test_billable_metadata_anthropic_when_true(self):
        """Test that $ai_billable metadata is True for Anthropic when billable=True."""
        llm = MaxChatAnthropic(user=self.user, team=self.team, model="claude", billable=True)

        mock_result = LLMResult(generations=[[Generation(text="Response")]])
        with patch("langchain_anthropic.ChatAnthropic.generate", return_value=mock_result) as mock_generate:
            messages: list[list[BaseMessage]] = [[HumanMessage(content="Test query")]]
            llm.generate(messages)

            call_kwargs = mock_generate.call_args.kwargs
            self.assertIn("metadata", call_kwargs)
            self.assertIn("posthog_properties", call_kwargs["metadata"])
            self.assertEqual(call_kwargs["metadata"]["posthog_properties"]["$ai_billable"], True)
            self.assertEqual(call_kwargs["metadata"]["posthog_properties"]["team_id"], self.team.id)

    @parameterized.expand(
        [
            # (model_billable, is_agent_billable, expected_effective_billable, should_increment_counter)
            (True, True, True, False),  # Normal case: model wants billing, workflow allows it
            (True, False, False, True),  # Impersonation: model wants billing, workflow blocks it
            (False, True, False, False),  # Model doesn't want billing, workflow allows it
            (False, False, False, False),  # Neither wants billing
        ]
    )
    def test_get_effective_billable(
        self, model_billable: bool, is_agent_billable: bool, expected: bool, should_increment_counter: bool
    ):
        llm = MaxChatOpenAI(user=self.user, team=self.team, billable=model_billable)

        config = {"configurable": {"is_agent_billable": is_agent_billable}}

        with (
            patch("ee.hogai.llm.ensure_config", return_value=config),
            patch.object(BILLING_SKIPPED_COUNTER, "labels") as mock_labels,
        ):
            result = llm._get_effective_billable()

        self.assertEqual(result, expected)

        if should_increment_counter:
            expected_model = getattr(llm, "model", None) or getattr(llm, "model_name", "unknown")
            mock_labels.assert_called_once_with(model=expected_model)
            mock_labels.return_value.inc.assert_called_once()
        else:
            mock_labels.return_value.inc.assert_not_called()

    def test_workflow_billing_override_in_generate(self):
        """Test that workflow-level is_agent_billable=False overrides model billable=True in generate."""
        llm = MaxChatOpenAI(user=self.user, team=self.team, use_responses_api=False, billable=True)

        mock_result = LLMResult(generations=[[Generation(text="Response")]])
        config = {"configurable": {"is_agent_billable": False}}

        with (
            patch("langchain_openai.ChatOpenAI.generate", return_value=mock_result) as mock_generate,
            patch("ee.hogai.llm.ensure_config", return_value=config),
        ):
            messages: list[list[BaseMessage]] = [[HumanMessage(content="Test query")]]
            llm.generate(messages)

            call_kwargs = mock_generate.call_args.kwargs
            self.assertEqual(call_kwargs["metadata"]["posthog_properties"]["$ai_billable"], False)

    async def test_workflow_billing_override_in_agenerate(self):
        """Test that workflow-level is_agent_billable=False overrides model billable=True in agenerate."""
        llm = MaxChatAnthropic(user=self.user, team=self.team, model="claude", billable=True)

        mock_result = LLMResult(generations=[[Generation(text="Response")]])
        config = {"configurable": {"is_agent_billable": False}}

        with (
            patch("langchain_anthropic.ChatAnthropic.agenerate", return_value=mock_result) as mock_agenerate,
            patch("ee.hogai.llm.ensure_config", return_value=config),
        ):
            messages: list[list[BaseMessage]] = [[HumanMessage(content="Test query")]]
            await llm.agenerate(messages)

            call_kwargs = mock_agenerate.call_args.kwargs
            self.assertEqual(call_kwargs["metadata"]["posthog_properties"]["$ai_billable"], False)

    def test_effective_billable_defaults_to_true_when_no_config(self):
        """Test that is_agent_billable defaults to True when not in config."""
        llm = MaxChatOpenAI(user=self.user, team=self.team, billable=True)

        with patch("ee.hogai.llm.ensure_config", return_value={}):
            result = llm._get_effective_billable()

        self.assertTrue(result)
