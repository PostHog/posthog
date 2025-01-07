from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from langchain_core.runnables import RunnableLambda

from ee.hogai.memory.nodes import (
    FAILED_SCRAPING_MESSAGE,
    MemoryInitializerContextMixin,
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
