from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from freezegun import freeze_time
from langchain_core.messages import AIMessage as LangchainAIMessage, ToolMessage as LangchainToolMessage
from langchain_core.runnables import RunnableLambda
from langgraph.errors import NodeInterrupt

from ee.hogai.graph.memory import prompts
from ee.hogai.graph.memory.nodes import (
    MemoryCollectorNode,
    MemoryCollectorToolsNode,
    MemoryInitializerContextMixin,
    MemoryInitializerInterruptNode,
    MemoryInitializerNode,
    MemoryOnboardingEnquiryInterruptNode,
    MemoryOnboardingFinalizeNode,
    MemoryOnboardingNode,
    MemoryOnboardingEnquiryNode,
)
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.models import CoreMemory
from posthog.schema import AssistantMessage, EventTaxonomyItem, HumanMessage
from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
)


@override_settings(IN_UNIT_TESTING=True)
class TestMemoryInitializerContextMixin(ClickhouseTestMixin, BaseTest):
    def get_mixin(self):
        mixin = MemoryInitializerContextMixin()
        mixin._team = self.team
        return mixin

    def test_domain_retrieval(self):
        _create_person(
            distinct_ids=["person1"],
            team=self.team,
        )
        _create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            properties={"$host": "us.posthog.com"},
        )
        _create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            properties={"$host": "eu.posthog.com"},
        )

        _create_person(
            distinct_ids=["person2"],
            team=self.team,
        )
        _create_event(
            event="$pageview",
            distinct_id="person2",
            team=self.team,
            properties={"$host": "us.posthog.com"},
        )

        mixin = self.get_mixin()
        self.assertEqual(
            mixin._retrieve_context(),
            [EventTaxonomyItem(property="$host", sample_values=["us.posthog.com", "eu.posthog.com"], sample_count=2)],
        )

    def test_app_bundle_id_retrieval(self):
        _create_person(
            distinct_ids=["person1"],
            team=self.team,
        )
        _create_event(
            event=f"$screen",
            distinct_id="person1",
            team=self.team,
            properties={"$app_namespace": "com.posthog.app"},
        )
        _create_event(
            event=f"$screen",
            distinct_id="person1",
            team=self.team,
            properties={"$app_namespace": "com.posthog"},
        )

        _create_person(
            distinct_ids=["person2"],
            team=self.team,
        )
        _create_event(
            event=f"$screen",
            distinct_id="person2",
            team=self.team,
            properties={"$app_namespace": "com.posthog.app"},
        )

        mixin = self.get_mixin()
        self.assertEqual(
            mixin._retrieve_context(),
            [
                EventTaxonomyItem(
                    property="$app_namespace", sample_values=["com.posthog.app", "com.posthog"], sample_count=2
                )
            ],
        )


@override_settings(IN_UNIT_TESTING=True)
class TestMemoryOnboardingNode(ClickhouseTestMixin, BaseTest):
    def _set_up_pageview_events(self):
        _create_person(
            distinct_ids=["person1"],
            team=self.team,
        )
        _create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            properties={"$host": "us.posthog.com"},
        )

    def _set_up_app_bundle_id_events(self):
        _create_person(
            distinct_ids=["person1"],
            team=self.team,
        )
        _create_event(
            event="$screen",
            distinct_id="person1",
            team=self.team,
            properties={"$app_namespace": "com.posthog.app"},
        )

    def test_should_run(self):
        node = MemoryOnboardingNode(team=self.team, user=self.user)
        self.assertEqual(
            node.should_run_onboarding_at_start(
                AssistantState(messages=[HumanMessage(content=prompts.ONBOARDING_INITIAL_MESSAGE)])
            ),
            "memory_onboarding",
        )

        core_memory = CoreMemory.objects.create(team=self.team)
        self.assertEqual(
            node.should_run_onboarding_at_start(AssistantState(messages=[HumanMessage(content="Hello")])), "continue"
        )

        core_memory.change_status_to_pending()
        self.assertEqual(
            node.should_run_onboarding_at_start(AssistantState(messages=[HumanMessage(content="Hello")])), "continue"
        )

        core_memory.change_status_to_skipped()
        self.assertEqual(
            node.should_run_onboarding_at_start(AssistantState(messages=[HumanMessage(content="Hello")])), "continue"
        )

    def test_router(self):
        node = MemoryOnboardingNode(team=self.team, user=self.user)
        self.assertEqual(node.router(AssistantState(messages=[HumanMessage(content="Hello")])), "initialize_memory")
        core_memory = CoreMemory.objects.create(team=self.team)
        core_memory.initial_text = "Some initial text"
        core_memory.save()
        self.assertEqual(node.router(AssistantState(messages=[HumanMessage(content="Hello")])), "onboarding_enquiry")

    def test_onboarding_initial_message_is_sent_if_no_events(self):
        node = MemoryOnboardingNode(team=self.team, user=self.user)
        new_state = node.run(AssistantState(messages=[HumanMessage(content="Hello")]), {})
        self.assertEqual(len(new_state.messages), 1)
        self.assertTrue(isinstance(new_state.messages[0], AssistantMessage))
        self.assertEqual(new_state.messages[0].content, prompts.ENQUIRY_INITIAL_MESSAGE)

    def test_node_uses_project_description(self):
        self.team.project.product_description = "This is a product analytics platform"
        self.team.project.save()

        node = MemoryOnboardingNode(team=self.team, user=self.user)
        new_state = node.run(AssistantState(messages=[HumanMessage(content="Hello")]), {})
        self.assertEqual(len(new_state.messages), 1)
        self.assertTrue(isinstance(new_state.messages[0], AssistantMessage))
        self.assertEqual(new_state.messages[0].content, prompts.ENQUIRY_INITIAL_MESSAGE)

        core_memory = CoreMemory.objects.get(team=self.team)
        self.assertEqual(
            core_memory.initial_text,
            "Question: What does the company do?\nAnswer: This is a product analytics platform",
        )

    def test_node_starts_onboarding_for_pageview_events(self):
        self._set_up_pageview_events()
        node = MemoryOnboardingNode(team=self.team, user=self.user)
        new_state = node.run(AssistantState(messages=[HumanMessage(content="Hello")]), {})
        self.assertEqual(len(new_state.messages), 1)
        self.assertTrue(isinstance(new_state.messages[0], AssistantMessage))

        core_memory = CoreMemory.objects.get(team=self.team)
        self.assertEqual(core_memory.scraping_status, CoreMemory.ScrapingStatus.PENDING)
        self.assertIsNotNone(core_memory.scraping_started_at)

    def test_node_starts_onboarding_for_app_bundle_id_events(self):
        self._set_up_app_bundle_id_events()
        node = MemoryOnboardingNode(team=self.team, user=self.user)
        new_state = node.run(AssistantState(messages=[HumanMessage(content="Hello")]), {})
        self.assertEqual(len(new_state.messages), 1)
        self.assertTrue(isinstance(new_state.messages[0], AssistantMessage))

        core_memory = CoreMemory.objects.get(team=self.team)
        self.assertEqual(core_memory.scraping_status, CoreMemory.ScrapingStatus.PENDING)
        self.assertIsNotNone(core_memory.scraping_started_at)


@override_settings(IN_UNIT_TESTING=True)
class TestMemoryInitializerNode(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.core_memory = CoreMemory.objects.create(
            team=self.team,
            scraping_status=CoreMemory.ScrapingStatus.PENDING,
            scraping_started_at=timezone.now(),
        )

    def _set_up_pageview_events(self):
        _create_person(
            distinct_ids=["person1"],
            team=self.team,
        )
        _create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            properties={"$host": "us.posthog.com"},
        )

    def _set_up_app_bundle_id_events(self):
        _create_person(
            distinct_ids=["person1"],
            team=self.team,
        )
        _create_event(
            event="$screen",
            distinct_id="person1",
            team=self.team,
            properties={"$app_namespace": "com.posthog.app"},
        )

    def test_router_with_failed_scraping_message(self):
        node = MemoryInitializerNode(team=self.team, user=self.user)
        state = AssistantState(messages=[AssistantMessage(content=prompts.SCRAPING_SUCCESS_MESSAGE)])
        self.assertEqual(node.router(state), "interrupt")

    def test_router_with_other_message(self):
        node = MemoryInitializerNode(team=self.team, user=self.user)
        state = AssistantState(messages=[AssistantMessage(content="Some other message")])
        self.assertEqual(node.router(state), "continue")

    def test_should_process_message_chunk_with_no_data_available(self):
        from langchain_core.messages import AIMessageChunk

        chunk = AIMessageChunk(content="no data available.")
        self.assertFalse(MemoryInitializerNode.should_process_message_chunk(chunk))

        chunk = AIMessageChunk(content="NO DATA AVAILABLE for something")
        self.assertFalse(MemoryInitializerNode.should_process_message_chunk(chunk))

    def test_should_process_message_chunk_with_valid_data(self):
        from langchain_core.messages import AIMessageChunk

        chunk = AIMessageChunk(content="PostHog is an open-source product analytics platform")
        self.assertTrue(MemoryInitializerNode.should_process_message_chunk(chunk))

        chunk = AIMessageChunk(content="This is a valid message that should be processed")
        self.assertTrue(MemoryInitializerNode.should_process_message_chunk(chunk))

    def test_format_message_removes_reference_tags(self):
        message = "PostHog[1] is a product analytics platform[2]. It helps track user behavior[3]."
        expected = (
            prompts.SCRAPING_SUCCESS_MESSAGE + "PostHog is a product analytics platform. It helps track user behavior."
        )
        self.assertEqual(MemoryInitializerNode.format_message(message), expected)

    def test_format_message_with_no_reference_tags(self):
        message = "PostHog is a product analytics platform. It helps track user behavior."
        expected = prompts.SCRAPING_SUCCESS_MESSAGE + message
        self.assertEqual(MemoryInitializerNode.format_message(message), expected)

    def test_run_with_url_based_initialization(self):
        with patch.object(MemoryInitializerNode, "_model") as model_mock:
            model_mock.return_value = RunnableLambda(lambda _: "PostHog is a product analytics platform.")

            self._set_up_pageview_events()
            node = MemoryInitializerNode(team=self.team, user=self.user)

            new_state = node.run(AssistantState(messages=[HumanMessage(content="Hello")]), {})
            self.assertEqual(len(new_state.messages), 1)
            self.assertIsInstance(new_state.messages[0], AssistantMessage)
            self.assertEqual(
                new_state.messages[0].content,
                prompts.SCRAPING_SUCCESS_MESSAGE + "PostHog is a product analytics platform.",
            )

            core_memory = CoreMemory.objects.get(team=self.team)
            self.assertEqual(core_memory.scraping_status, CoreMemory.ScrapingStatus.PENDING)

        flush_persons_and_events()

    def test_run_with_app_bundle_id_initialization(self):
        with (
            patch.object(MemoryInitializerNode, "_model") as model_mock,
            patch.object(MemoryInitializerNode, "_retrieve_context") as context_mock,
        ):
            context_mock.return_value = [
                EventTaxonomyItem(property="$app_namespace", sample_values=["com.posthog.app"], sample_count=1)
            ]
            model_mock.return_value = RunnableLambda(lambda _: "PostHog mobile app description.")

            self._set_up_app_bundle_id_events()
            node = MemoryInitializerNode(team=self.team, user=self.user)

            new_state = node.run(AssistantState(messages=[HumanMessage(content="Hello")]), {})
            self.assertEqual(len(new_state.messages), 1)
            self.assertIsInstance(new_state.messages[0], AssistantMessage)
            self.assertEqual(
                new_state.messages[0].content, prompts.SCRAPING_SUCCESS_MESSAGE + "PostHog mobile app description."
            )

            core_memory = CoreMemory.objects.get(team=self.team)
            self.assertEqual(core_memory.scraping_status, CoreMemory.ScrapingStatus.PENDING)

        flush_persons_and_events()

    def test_run_with_no_data_available(self):
        with (
            patch.object(MemoryInitializerNode, "_model") as model_mock,
            patch.object(MemoryInitializerNode, "_retrieve_context") as context_mock,
        ):
            node = MemoryInitializerNode(team=self.team, user=self.user)

            model_mock.return_value = RunnableLambda(lambda _: "no data available.")
            context_mock.return_value = []
            new_state = node.run(AssistantState(messages=[HumanMessage(content="Hello")]), {})
            self.assertEqual(new_state, PartialAssistantState(messages=[]))

            context_mock.return_value = [
                EventTaxonomyItem(property="$host", sample_values=["us.posthog.com"], sample_count=1)
            ]

            new_state = node.run(AssistantState(messages=[HumanMessage(content="Hello")]), {})
            self.assertEqual(len(new_state.messages), 1)
            self.assertTrue(isinstance(new_state.messages[0], AssistantMessage))
            self.assertEqual(new_state.messages[0].content, prompts.SCRAPING_TERMINATION_MESSAGE)


@override_settings(IN_UNIT_TESTING=True)
class TestMemoryInitializerInterruptNode(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.core_memory = CoreMemory.objects.create(
            team=self.team,
            scraping_status=CoreMemory.ScrapingStatus.PENDING,
            scraping_started_at=timezone.now(),
        )
        self.node = MemoryInitializerInterruptNode(team=self.team, user=self.user)

    def test_interrupt_when_not_resumed(self):
        state = AssistantState(messages=[AssistantMessage(content="Product description")])

        with self.assertRaises(NodeInterrupt) as e:
            self.node.run(state, {})

        interrupt_message = e.exception.args[0][0].value
        self.assertIsInstance(interrupt_message, AssistantMessage)
        self.assertEqual(interrupt_message.content, prompts.SCRAPING_VERIFICATION_MESSAGE)
        self.assertIsNotNone(interrupt_message.meta)
        self.assertEqual(len(interrupt_message.meta.form.options), 2)
        self.assertEqual(interrupt_message.meta.form.options[0].value, prompts.SCRAPING_CONFIRMATION_MESSAGE)
        self.assertEqual(interrupt_message.meta.form.options[1].value, prompts.SCRAPING_REJECTION_MESSAGE)


@override_settings(IN_UNIT_TESTING=True)
class TestMemoryOnboardingEnquiryNode(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.core_memory = CoreMemory.objects.create(team=self.team)
        self.node = MemoryOnboardingEnquiryNode(team=self.team, user=self.user)

    def test_router_with_no_core_memory(self):
        self.core_memory.delete()
        with self.assertRaises(ValueError) as e:
            self.node.router(AssistantState(messages=[]))
        self.assertEqual(str(e.exception), "No core memory found.")

    def test_router_with_no_onboarding_question(self):
        self.assertEqual(self.node.router(AssistantState(messages=[])), "continue")

    def test_router_with_onboarding_question(self):
        self.assertEqual(
            self.node.router(AssistantState(messages=[], onboarding_question="What is your target market?")),
            "interrupt",
        )

    def test_format_question_with_separator(self):
        question = "Some prefix===What is your target market?"
        self.assertEqual(self.node._format_question(question), "What is your target market?")

    def test_format_question_without_separator(self):
        question = "What is your target market?"
        self.assertEqual(self.node._format_question(question), question)

    def test_format_question_with_markdown(self):
        question = "**What** is your _target_ market?"
        self.assertEqual(self.node._format_question(question), "What is your target market?")

    def test_format_memory(self):
        markdown_text = "# Product Description\n\n- Feature 1\n- Feature 2\n\n**Bold text** and `code` [1]"
        expected = "Product Description\n\nFeature 1\nFeature 2\n\nBold text and code [1]"
        self.assertEqual(self.node._format_memory(markdown_text), expected)

    def test_run_with_initial_message(self):
        with patch.object(MemoryOnboardingEnquiryNode, "_model") as model_mock:
            model_mock.return_value = RunnableLambda(lambda _: "===What is your target market?")

            state = AssistantState(
                messages=[HumanMessage(content=prompts.ONBOARDING_INITIAL_MESSAGE)],
            )

            new_state = self.node.run(state, {})
            self.assertEqual(new_state.onboarding_question, "What is your target market?")

            self.core_memory.refresh_from_db()
            self.assertEqual(self.core_memory.initial_text, "Question: What is your target market?\nAnswer:")

    def test_run_with_answer(self):
        with patch.object(MemoryOnboardingEnquiryNode, "_model") as model_mock:
            model_mock.return_value = RunnableLambda(lambda _: "===What is your pricing model?")

            self.core_memory.append_question_to_initial_text("What is your target market?")
            state = AssistantState(
                messages=[HumanMessage(content="We target enterprise customers")],
            )

            new_state = self.node.run(state, {})
            self.assertEqual(new_state.onboarding_question, "What is your pricing model?")
            self.core_memory.refresh_from_db()
            self.assertEqual(
                self.core_memory.initial_text,
                "Question: What is your target market?\nAnswer: We target enterprise customers\nQuestion: What is your pricing model?\nAnswer:",
            )

    def test_run_with_all_questions_answered(self):
        with patch.object(MemoryOnboardingEnquiryNode, "_model") as model_mock:

            def mock_response(input_dict):
                input_str = str(input_dict)
                if "You are tasked with gathering information" in input_str:
                    return "===What is your target market?"
                return "[Done]"

            model_mock.return_value = RunnableLambda(mock_response)

            # First run - should get interrupted with first question
            state = AssistantState(
                messages=[HumanMessage(content=prompts.ONBOARDING_INITIAL_MESSAGE)],
            )
            new_state = self.node.run(state, {})
            self.assertEqual(new_state.onboarding_question, "What is your target market?")
            self.core_memory.refresh_from_db()
            self.assertEqual(self.core_memory.initial_text, "Question: What is your target market?\nAnswer:")

            # Second run - should complete since we have enough answers
            self.core_memory.append_question_to_initial_text("What is your pricing model?")
            self.core_memory.append_answer_to_initial_text("We use a subscription model")
            self.core_memory.append_question_to_initial_text("What is your target market?")
            state = AssistantState(
                messages=[HumanMessage(content="We target enterprise customers")],
            )
            new_state = self.node.run(state, {})
            self.assertEqual(new_state, PartialAssistantState(onboarding_question=""))

    def test_memory_accepted(self):
        with patch.object(MemoryOnboardingEnquiryNode, "_model") as model_mock:

            def mock_response(input_dict):
                input_str = str(input_dict)
                if "You are tasked with gathering information" in input_str:
                    return "===What is your target market?"
                return "[Done]"

            model_mock.return_value = RunnableLambda(mock_response)

            core_memory = CoreMemory.objects.get(team=self.team)
            core_memory.initial_text = "Question: What does the company do?\nAnswer: Product description"
            core_memory.save()
            state = AssistantState(
                messages=[
                    AssistantMessage(content="Product description"),
                    HumanMessage(content=prompts.SCRAPING_CONFIRMATION_MESSAGE),
                ],
            )

            new_state = self.node.run(state, {})
            self.assertEqual(new_state.onboarding_question, "What is your target market?")

            core_memory.refresh_from_db()
            self.assertEqual(
                core_memory.initial_text,
                "Question: What does the company do?\nAnswer: Product description\nQuestion: What is your target market?\nAnswer:",
            )

    def test_memory_rejected(self):
        with patch.object(MemoryOnboardingEnquiryNode, "_model") as model_mock:

            def mock_response(input_dict):
                input_str = str(input_dict)
                if "You are tasked with gathering information" in input_str:
                    return "===What is your target market?"
                return "[Done]"

            model_mock.return_value = RunnableLambda(mock_response)

            core_memory = CoreMemory.objects.get(team=self.team)
            core_memory.initial_text = "Question: What does the company do?\nAnswer: Product description"
            core_memory.save()
            state = AssistantState(
                messages=[
                    AssistantMessage(content="Product description"),
                    HumanMessage(content=prompts.SCRAPING_REJECTION_MESSAGE),
                ],
                graph_status="resumed",
            )

            new_state = self.node.run(state, {})
            self.assertEqual(new_state.onboarding_question, "What is your target market?")

            core_memory.refresh_from_db()
            self.assertEqual(core_memory.initial_text, "Question: What is your target market?\nAnswer:")


@override_settings(IN_UNIT_TESTING=True)
class TestMemoryEnquiryInterruptNode(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.core_memory = CoreMemory.objects.create(team=self.team)
        self.node = MemoryOnboardingEnquiryInterruptNode(team=self.team, user=self.user)

    def test_run(self):
        with self.assertRaises(NodeInterrupt) as e:
            self.node.run(
                AssistantState(
                    messages=[AssistantMessage(content="What is your name?"), HumanMessage(content="Hello")],
                    onboarding_question="What is your target market?",
                ),
                {},
            )
        self.assertEqual(len(e.exception.args[0]), 1)
        self.assertIsInstance(e.exception.args[0][0].value, AssistantMessage)
        self.assertEqual(e.exception.args[0][0].value.content, "What is your target market?")

        new_state = self.node.run(
            AssistantState(
                messages=[AssistantMessage(content="What is your target market?"), HumanMessage(content="Hello")],
                onboarding_question="What is your target market?",
            ),
            {},
        )
        self.assertEqual(new_state, PartialAssistantState(messages=[], onboarding_question=""))


@override_settings(IN_UNIT_TESTING=True)
class TestMemoryOnboardingFinalizeNode(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.core_memory = CoreMemory.objects.create(team=self.team)
        self.node = MemoryOnboardingFinalizeNode(team=self.team, user=self.user)

    def test_router(self):
        self.assertEqual(self.node.router(AssistantState(messages=[])), "continue")
        self.assertEqual(
            self.node.router(AssistantState(messages=[], root_tool_insight_plan="Insights plan")), "insights"
        )

    def test_run(self):
        with patch.object(MemoryOnboardingFinalizeNode, "_model") as model_mock:
            model_mock.return_value = RunnableLambda(lambda _: "Compressed memory about enterprise product")
            self.core_memory.initial_text = "Question: What does the company do?\nAnswer: Product description"
            self.core_memory.save()
            new_state = self.node.run(AssistantState(messages=[]), {})
            self.assertEqual(len(new_state.messages), 1)
            self.assertEqual(new_state.messages[0].content, prompts.SCRAPING_MEMORY_SAVED_MESSAGE)
            self.core_memory.refresh_from_db()
            self.assertEqual(self.core_memory.text, "Compressed memory about enterprise product")


@override_settings(IN_UNIT_TESTING=True)
class TestMemoryCollectorNode(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.core_memory = CoreMemory.objects.create(team=self.team)
        self.core_memory.set_core_memory("Test product core memory")
        self.node = MemoryCollectorNode(team=self.team, user=self.user)

    def test_router(self):
        # Test with no memory collection messages
        state = AssistantState(messages=[HumanMessage(content="Text")], memory_collection_messages=[])
        self.assertEqual(self.node.router(state), "next")

        # Test with memory collection messages
        state = AssistantState(
            messages=[HumanMessage(content="Text")],
            memory_collection_messages=[LangchainAIMessage(content="Memory message")],
        )
        self.assertEqual(self.node.router(state), "tools")

    def test_construct_messages(self):
        # Test basic conversation reconstruction
        state = AssistantState(
            messages=[
                HumanMessage(content="Question 1", id="0"),
                AssistantMessage(content="Answer 1", id="1"),
                HumanMessage(content="Question 2", id="2"),
            ],
            start_id="2",
        )
        history = self.node._construct_messages(state)
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0].content, "Question 1")
        self.assertEqual(history[1].content, "Answer 1")
        self.assertEqual(history[2].content, "Question 2")

        # Test with memory collection messages
        state = AssistantState(
            messages=[HumanMessage(content="Question", id="0")],
            memory_collection_messages=[
                LangchainAIMessage(content="Memory 1"),
                LangchainToolMessage(content="Tool response", tool_call_id="1"),
            ],
            start_id="0",
        )
        history = self.node._construct_messages(state)
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0].content, "Question")
        self.assertEqual(history[1].content, "Memory 1")
        self.assertEqual(history[2].content, "Tool response")

    @freeze_time("2024-01-01")
    def test_prompt_substitutions(self):
        with patch.object(MemoryCollectorNode, "_model") as model_mock:

            def assert_prompt(prompt):
                messages = prompt.to_messages()

                # Verify the structure of messages
                self.assertEqual(len(messages), 3)
                self.assertEqual(messages[0].type, "system")
                self.assertEqual(messages[1].type, "human")
                self.assertEqual(messages[2].type, "ai")

                # Verify system message content
                system_message = messages[0].content
                self.assertIn("Test product core memory", system_message)
                self.assertIn("2024-01-01", system_message)

                # Verify conversation messages
                self.assertEqual(messages[1].content, "We use a subscription model")
                self.assertEqual(messages[2].content, "Memory message")
                return LangchainAIMessage(content="[Done]")

            model_mock.return_value = RunnableLambda(assert_prompt)

            state = AssistantState(
                messages=[
                    HumanMessage(content="We use a subscription model", id="0"),
                ],
                memory_collection_messages=[
                    LangchainAIMessage(content="Memory message"),
                ],
                start_id="0",
            )

            self.node.run(state, {})

    def test_exits_on_done_message(self):
        with patch.object(MemoryCollectorNode, "_model") as model_mock:
            model_mock.return_value = RunnableLambda(
                lambda _: LangchainAIMessage(content="Processing complete. [Done]")
            )

            state = AssistantState(
                messages=[HumanMessage(content="Text")],
                memory_collection_messages=[LangchainAIMessage(content="Previous memory")],
            )

            new_state = self.node.run(state, {})
            self.assertEqual(new_state.memory_updated, True)
            self.assertEqual(new_state.memory_collection_messages, [])

    def test_appends_new_message(self):
        with patch.object(MemoryCollectorNode, "_model") as model_mock:
            model_mock.return_value = RunnableLambda(
                lambda _: LangchainAIMessage(
                    content="New memory",
                    tool_calls=[
                        {
                            "name": "core_memory_append",
                            "args": {"new_fragment": "New memory"},
                            "id": "1",
                        },
                    ],
                ),
            )

            state = AssistantState(
                messages=[HumanMessage(content="Text")],
                memory_collection_messages=[LangchainAIMessage(content="Previous memory")],
            )

            new_state = self.node.run(state, {})
            self.assertEqual(len(new_state.memory_collection_messages), 2)
            self.assertEqual(new_state.memory_collection_messages[0].content, "Previous memory")
            self.assertEqual(new_state.memory_collection_messages[1].content, "New memory")

    def test_construct_messages_typical_conversation(self):
        # Set up a typical conversation with multiple interactions
        state = AssistantState(
            messages=[
                HumanMessage(content="We use a subscription model", id="0"),
                AssistantMessage(content="I'll note that down", id="1"),
                HumanMessage(content="And we target enterprise customers", id="2"),
                AssistantMessage(content="Let me process that information", id="3"),
                HumanMessage(content="We also have a freemium tier", id="4"),
            ],
            memory_collection_messages=[
                LangchainAIMessage(content="Analyzing business model: subscription-based pricing."),
                LangchainToolMessage(content="Memory appended.", tool_call_id="1"),
                LangchainAIMessage(content="Analyzing target audience: enterprise customers."),
                LangchainToolMessage(content="Memory appended.", tool_call_id="2"),
            ],
            start_id="0",
        )

        history = self.node._construct_messages(state)

        # Verify the complete conversation history is reconstructed correctly
        self.assertEqual(len(history), 9)  # 5 conversation messages + 4 memory messages

        # Check conversation messages
        self.assertEqual(history[0].content, "We use a subscription model")
        self.assertEqual(history[1].content, "I'll note that down")
        self.assertEqual(history[2].content, "And we target enterprise customers")
        self.assertEqual(history[3].content, "Let me process that information")
        self.assertEqual(history[4].content, "We also have a freemium tier")

        # Check memory collection messages
        self.assertEqual(history[5].content, "Analyzing business model: subscription-based pricing.")
        self.assertEqual(history[6].content, "Memory appended.")
        self.assertEqual(history[7].content, "Analyzing target audience: enterprise customers.")
        self.assertEqual(history[8].content, "Memory appended.")


class TestMemoryCollectorToolsNode(BaseTest):
    def setUp(self):
        super().setUp()
        self.core_memory = CoreMemory.objects.create(team=self.team)
        self.core_memory.set_core_memory("Initial memory content")
        self.node = MemoryCollectorToolsNode(team=self.team, user=self.user)

    def test_handles_correct_tools(self):
        # Test handling a single append tool
        state = AssistantState(
            messages=[],
            memory_collection_messages=[
                LangchainAIMessage(
                    content="Adding new memory",
                    tool_calls=[
                        {
                            "name": "core_memory_append",
                            "args": {"memory_content": "New memory fragment."},
                            "id": "1",
                        },
                        {
                            "name": "core_memory_replace",
                            "args": {
                                "original_fragment": "Initial memory content",
                                "new_fragment": "New memory fragment 2.",
                            },
                            "id": "2",
                        },
                    ],
                )
            ],
        )

        new_state = self.node.run(state, {})
        self.assertEqual(len(new_state.memory_collection_messages), 3)
        self.assertEqual(new_state.memory_collection_messages[1].type, "tool")
        self.assertEqual(new_state.memory_collection_messages[1].content, "Memory appended.")
        self.assertEqual(new_state.memory_collection_messages[2].type, "tool")
        self.assertEqual(new_state.memory_collection_messages[2].content, "Memory replaced.")

    def test_handles_validation_error(self):
        # Test handling validation error with incorrect tool arguments
        state = AssistantState(
            messages=[],
            memory_collection_messages=[
                LangchainAIMessage(
                    content="Invalid tool call",
                    tool_calls=[
                        {
                            "name": "core_memory_append",
                            "args": {"invalid_arg": "This will fail"},
                            "id": "1",
                        }
                    ],
                )
            ],
        )

        new_state = self.node.run(state, {})
        self.assertEqual(len(new_state.memory_collection_messages), 2)
        self.assertNotIn("{{validation_error_message}}", new_state.memory_collection_messages[1].content)

    def test_handles_multiple_tools(self):
        # Test handling multiple tool calls in a single message
        state = AssistantState(
            messages=[],
            memory_collection_messages=[
                LangchainAIMessage(
                    content="Multiple operations",
                    tool_calls=[
                        {
                            "name": "core_memory_append",
                            "args": {"memory_content": "First memory"},
                            "id": "1",
                        },
                        {
                            "name": "core_memory_append",
                            "args": {"memory_content": "Second memory"},
                            "id": "2",
                        },
                        {
                            "name": "core_memory_replace",
                            "args": {
                                "original_fragment": "Initial memory content",
                                "new_fragment": "Third memory",
                            },
                            "id": "3",
                        },
                    ],
                )
            ],
        )

        new_state = self.node.run(state, {})
        self.assertEqual(len(new_state.memory_collection_messages), 4)
        self.assertEqual(new_state.memory_collection_messages[1].content, "Memory appended.")
        self.assertEqual(new_state.memory_collection_messages[1].type, "tool")
        self.assertEqual(new_state.memory_collection_messages[1].tool_call_id, "1")
        self.assertEqual(new_state.memory_collection_messages[2].content, "Memory appended.")
        self.assertEqual(new_state.memory_collection_messages[2].type, "tool")
        self.assertEqual(new_state.memory_collection_messages[2].tool_call_id, "2")
        self.assertEqual(new_state.memory_collection_messages[3].content, "Memory replaced.")
        self.assertEqual(new_state.memory_collection_messages[3].type, "tool")
        self.assertEqual(new_state.memory_collection_messages[3].tool_call_id, "3")

        self.core_memory.refresh_from_db()
        self.assertEqual(self.core_memory.text, "Third memory\nFirst memory\nSecond memory")

    def test_handles_replacing_memory(self):
        # Test replacing a memory fragment
        state = AssistantState(
            messages=[],
            memory_collection_messages=[
                LangchainAIMessage(
                    content="Replacing memory",
                    tool_calls=[
                        {
                            "name": "core_memory_replace",
                            "args": {
                                "original_fragment": "Initial memory",
                                "new_fragment": "Updated memory",
                            },
                            "id": "1",
                        }
                    ],
                )
            ],
        )

        new_state = self.node.run(state, {})
        self.assertEqual(len(new_state.memory_collection_messages), 2)
        self.assertEqual(new_state.memory_collection_messages[1].content, "Memory replaced.")
        self.assertEqual(new_state.memory_collection_messages[1].type, "tool")
        self.assertEqual(new_state.memory_collection_messages[1].tool_call_id, "1")
        self.core_memory.refresh_from_db()
        self.assertEqual(self.core_memory.text, "Updated memory content")

    def test_handles_replace_memory_not_found(self):
        # Test replacing a memory fragment that doesn't exist
        state = AssistantState(
            messages=[],
            memory_collection_messages=[
                LangchainAIMessage(
                    content="Replacing non-existent memory",
                    tool_calls=[
                        {
                            "name": "core_memory_replace",
                            "args": {
                                "original_fragment": "Non-existent memory",
                                "new_fragment": "New memory",
                            },
                            "id": "1",
                        }
                    ],
                )
            ],
        )

        new_state = self.node.run(state, {})
        self.assertEqual(len(new_state.memory_collection_messages), 2)
        self.assertIn("not found", new_state.memory_collection_messages[1].content.lower())
        self.assertEqual(new_state.memory_collection_messages[1].type, "tool")
        self.assertEqual(new_state.memory_collection_messages[1].tool_call_id, "1")
        self.core_memory.refresh_from_db()
        self.assertEqual(self.core_memory.text, "Initial memory content")

    def test_handles_appending_new_memory(self):
        # Test appending a new memory fragment
        state = AssistantState(
            messages=[],
            memory_collection_messages=[
                LangchainAIMessage(
                    content="Appending memory",
                    tool_calls=[
                        {
                            "name": "core_memory_append",
                            "args": {"memory_content": "Additional memory"},
                            "id": "1",
                        }
                    ],
                )
            ],
        )

        new_state = self.node.run(state, {})
        self.assertEqual(len(new_state.memory_collection_messages), 2)
        self.assertEqual(new_state.memory_collection_messages[1].content, "Memory appended.")
        self.assertEqual(new_state.memory_collection_messages[1].type, "tool")
        self.core_memory.refresh_from_db()
        self.assertEqual(self.core_memory.text, "Initial memory content\nAdditional memory")

    def test_error_when_no_memory_collection_messages(self):
        # Test error when no memory collection messages are present
        state = AssistantState(messages=[], memory_collection_messages=[])

        with self.assertRaises(ValueError) as e:
            self.node.run(state, {})
        self.assertEqual(str(e.exception), "No memory collection messages found.")

    def test_error_when_last_message_not_ai(self):
        # Test error when last message is not an AI message
        state = AssistantState(
            messages=[],
            memory_collection_messages=[LangchainToolMessage(content="Not an AI message", tool_call_id="1")],
        )

        with self.assertRaises(ValueError) as e:
            self.node.run(state, {})
        self.assertEqual(str(e.exception), "Last message must be an AI message.")

    def test_error_when_no_core_memory(self):
        # Test error when core memory is not found
        self.core_memory.delete()
        state = AssistantState(
            messages=[],
            memory_collection_messages=[
                LangchainAIMessage(
                    content="Memory operation",
                    tool_calls=[
                        {
                            "name": "core_memory_append",
                            "args": {"memory_content": "New memory"},
                            "id": "1",
                        }
                    ],
                )
            ],
        )

        with self.assertRaises(ValueError) as e:
            self.node.run(state, {})
        self.assertEqual(str(e.exception), "No core memory found.")
