from django.test import override_settings

from ee.hogai.memory.nodes import MemoryInitializerContextMixin, MemoryOnboardingNode
from ee.hogai.utils.types import AssistantState
from ee.models import CoreMemory
from posthog.schema import AssistantMessage, EventTaxonomyItem, HumanMessage
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person


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
