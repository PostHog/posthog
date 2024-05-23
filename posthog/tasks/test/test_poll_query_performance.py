from posthog.tasks.poll_query_performance import query_manager_from_initial_query_id
from posthog.test.base import BaseTest


class TestPollQueryPerformance(BaseTest):
    def test_query_manager_from_initial_query_id_succeeds(self):
        self.assertIsNotNone(query_manager_from_initial_query_id("1_00008400-e29b-41d4-a716-446655440000_fwefwef"))
        self.assertIsNotNone(query_manager_from_initial_query_id("123123_550e8400-e29b-41d4-a716-446655440000_fwefwef"))

    def test_query_manager_from_initial_query_id_fails(self):
        self.assertIsNone(query_manager_from_initial_query_id("550e8400-e29b-41d4-a716-446655440000"))
        self.assertIsNone(query_manager_from_initial_query_id("fewf_550e8400-e29b-41d4-a716-446655440000_fwefwef"))
        self.assertIsNone(query_manager_from_initial_query_id("1a_550e8400-e29b-41d4-a716-446655440000_fwefwef"))
