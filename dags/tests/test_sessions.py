from posthog.test.base import APIBaseTest

from posthog.clickhouse.client import sync_execute

from dags.sessions import unmerged_parts_query


class TestSessionsDags(APIBaseTest):
    def test_get_number_of_unmerged_parts(self):
        # Just test that the query succeeds without errors and returns an int.
        # We can't really guarantee anything about the number of parts on the test DB.
        result = sync_execute(unmerged_parts_query)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0][0], int)
