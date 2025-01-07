from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from freezegun import freeze_time
from langchain_core.messages import AIMessage as LangchainAIMessage, ToolMessage as LangchainToolMessage
from langchain_core.runnables import RunnableLambda
from langgraph.errors import NodeInterrupt

from ee.hogai.memory.nodes import (
    FAILED_SCRAPING_MESSAGE,
    MemoryCollectorNode,
    MemoryInitializerContextMixin,
    MemoryInitializerInterruptNode,
    MemoryInitializerNode,
    MemoryOnboardingNode,
)
from ee.hogai.utils.types import AssistantState
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
        node = MemoryOnboardingNode(team=self.team)
        self.assertTrue(node.should_run(AssistantState(messages=[])))

        core_memory = CoreMemory.objects.create(team=self.team)
        self.assertTrue(node.should_run(AssistantState(messages=[])))

        core_memory.change_status_to_pending()
        self.assertFalse(node.should_run(AssistantState(messages=[])))

        core_memory.change_status_to_skipped()
        self.assertFalse(node.should_run(AssistantState(messages=[])))

        core_memory.set_core_memory("Hello World")
        self.assertFalse(node.should_run(AssistantState(messages=[])))

    def test_router(self):
        node = MemoryOnboardingNode(team=self.team)
        self.assertEqual(node.router(AssistantState(messages=[HumanMessage(content="Hello")])), "continue")
        self.assertEqual(
            node.router(AssistantState(messages=[HumanMessage(content="Hello"), AssistantMessage(content="world")])),
            "initialize_memory",
        )

    def test_node_skips_onboarding_if_no_events(self):
        node = MemoryOnboardingNode(team=self.team)
        self.assertIsNone(node.run(AssistantState(messages=[HumanMessage(content="Hello")]), {}))

    def test_node_starts_onboarding_for_pageview_events(self):
        self._set_up_pageview_events()
        node = MemoryOnboardingNode(team=self.team)
        new_state = node.run(AssistantState(messages=[HumanMessage(content="Hello")]), {})
        self.assertEqual(len(new_state.messages), 1)
        self.assertTrue(isinstance(new_state.messages[0], AssistantMessage))

        core_memory = CoreMemory.objects.get(team=self.team)
        self.assertEqual(core_memory.scraping_status, CoreMemory.ScrapingStatus.PENDING)
        self.assertIsNotNone(core_memory.scraping_started_at)

    def test_node_starts_onboarding_for_app_bundle_id_events(self):
        self._set_up_app_bundle_id_events()
        node = MemoryOnboardingNode(team=self.team)
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
        node = MemoryInitializerNode(team=self.team)
        state = AssistantState(messages=[AssistantMessage(content=FAILED_SCRAPING_MESSAGE)])
        self.assertEqual(node.router(state), "continue")

    def test_router_with_other_message(self):
        node = MemoryInitializerNode(team=self.team)
        state = AssistantState(messages=[AssistantMessage(content="Some other message")])
        self.assertEqual(node.router(state), "interrupt")

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
        expected = "PostHog is a product analytics platform. It helps track user behavior."
        self.assertEqual(MemoryInitializerNode.format_message(message), expected)

    def test_format_message_with_no_reference_tags(self):
        message = "PostHog is a product analytics platform. It helps track user behavior."
        self.assertEqual(MemoryInitializerNode.format_message(message), message)

    def test_run_with_url_based_initialization(self):
        with patch.object(MemoryInitializerNode, "_model") as model_mock:
            model_mock.return_value = RunnableLambda(lambda _: "PostHog is a product analytics platform.")

            self._set_up_pageview_events()
            node = MemoryInitializerNode(team=self.team)

            new_state = node.run(AssistantState(messages=[HumanMessage(content="Hello")]), {})
            self.assertEqual(len(new_state.messages), 1)
            self.assertIsInstance(new_state.messages[0], AssistantMessage)
            self.assertEqual(new_state.messages[0].content, "PostHog is a product analytics platform.")

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
            node = MemoryInitializerNode(team=self.team)

            new_state = node.run(AssistantState(messages=[HumanMessage(content="Hello")]), {})
            self.assertEqual(len(new_state.messages), 1)
            self.assertIsInstance(new_state.messages[0], AssistantMessage)
            self.assertEqual(new_state.messages[0].content, "PostHog mobile app description.")

            core_memory = CoreMemory.objects.get(team=self.team)
            self.assertEqual(core_memory.scraping_status, CoreMemory.ScrapingStatus.PENDING)

        flush_persons_and_events()

    def test_run_with_no_data_available(self):
        with (
            patch.object(MemoryInitializerNode, "_model") as model_mock,
            patch.object(MemoryInitializerNode, "_retrieve_context") as context_mock,
        ):
            model_mock.return_value = RunnableLambda(lambda _: "no data available.")
            context_mock.return_value = []

            node = MemoryInitializerNode(team=self.team)

            with self.assertRaises(ValueError) as e:
                node.run(AssistantState(messages=[HumanMessage(content="Hello")]), {})
            self.assertEqual(str(e.exception), "No host or app bundle ID found in the memory initializer.")


@override_settings(IN_UNIT_TESTING=True)
class TestMemoryInitializerInterruptNode(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.core_memory = CoreMemory.objects.create(
            team=self.team,
            scraping_status=CoreMemory.ScrapingStatus.PENDING,
            scraping_started_at=timezone.now(),
        )
        self.node = MemoryInitializerInterruptNode(team=self.team)

    def test_interrupt_when_not_resumed(self):
        state = AssistantState(messages=[AssistantMessage(content="Product description")])

        with self.assertRaises(NodeInterrupt) as e:
            self.node.run(state, {})

        interrupt_message = e.exception.args[0][0].value
        self.assertIsInstance(interrupt_message, AssistantMessage)
        self.assertEqual(interrupt_message.content, "Does it look like a good summary of what your product does?")
        self.assertIsNotNone(interrupt_message.meta)
        self.assertEqual(len(interrupt_message.meta.form.options), 2)
        self.assertEqual(interrupt_message.meta.form.options[0].value, "Yes, save this.")
        self.assertEqual(interrupt_message.meta.form.options[1].value, "No, this doesn't look right.")

    def test_memory_accepted(self):
        with patch.object(MemoryInitializerInterruptNode, "_model") as model_mock:
            model_mock.return_value = RunnableLambda(lambda _: "Compressed memory")

            state = AssistantState(
                messages=[
                    AssistantMessage(content="Product description"),
                    HumanMessage(content="Yes, save this."),
                ],
                resumed=True,
            )

            new_state = self.node.run(state, {})

            self.assertEqual(len(new_state.messages), 1)
            self.assertIsInstance(new_state.messages[0], AssistantMessage)
            self.assertEqual(
                new_state.messages[0].content,
                "Thanks! I've updated my initial memory. Let me help with your request.",
            )

            core_memory = CoreMemory.objects.get(team=self.team)
            self.assertEqual(core_memory.text, "Compressed memory")

    def test_memory_rejected(self):
        state = AssistantState(
            messages=[
                AssistantMessage(content="Product description"),
                HumanMessage(content="No, this doesn't look right."),
            ],
            resumed=True,
        )

        new_state = self.node.run(state, {})

        self.assertEqual(len(new_state.messages), 1)
        self.assertIsInstance(new_state.messages[0], AssistantMessage)
        self.assertEqual(
            new_state.messages[0].content,
            "All right, let's skip this step. You could edit my initial memory in Settings.",
        )

    def test_error_when_last_message_not_human(self):
        state = AssistantState(
            messages=[AssistantMessage(content="Product description")],
            resumed=True,
        )

        with self.assertRaises(ValueError) as e:
            self.node.run(state, {})
        self.assertEqual(str(e.exception), "Last message is not a human message.")

    def test_error_when_no_core_memory(self):
        self.core_memory.delete()

        state = AssistantState(
            messages=[
                AssistantMessage(content="Product description"),
                HumanMessage(content="Yes, save this."),
            ],
            resumed=True,
        )

        with self.assertRaises(ValueError) as e:
            self.node.run(state, {})
        self.assertEqual(str(e.exception), "No core memory found.")

    def test_error_when_no_memory_message(self):
        state = AssistantState(
            messages=[HumanMessage(content="Yes, save this.")],
            resumed=True,
        )

        with self.assertRaises(ValueError) as e:
            self.node.run(state, {})
        self.assertEqual(str(e.exception), "No memory message found.")

    def test_format_memory(self):
        markdown_text = "# Product Description\n\n- Feature 1\n- Feature 2\n\n**Bold text** and `code` [1]"
        expected = "Product Description\n\nFeature 1\nFeature 2\n\nBold text and code [1]"
        self.assertEqual(self.node._format_memory(markdown_text), expected)


@override_settings(IN_UNIT_TESTING=True)
class TestMemoryCollectorNode(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.core_memory = CoreMemory.objects.create(team=self.team)
        self.core_memory.set_core_memory("Test product core memory")
        self.node = MemoryCollectorNode(team=self.team)

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
