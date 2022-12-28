from unittest.mock import patch

import fakeredis
from clickhouse_driver.errors import ServerException
from django.test import TestCase

from posthog.clickhouse.client import execute_async as client
from posthog.client import sync_execute
from posthog.test.base import ClickhouseTestMixin


class ClickhouseClientTestCase(TestCase, ClickhouseTestMixin):
    def setUp(self):
        self.redis_client = fakeredis.FakeStrictRedis()

    def test_async_query_client(self):
        query = "SELECT 1+1"
        team_id = 2
        query_id = client.enqueue_execute_with_progress(team_id, query, bypass_celery=True)
        result = client.get_status_or_results(team_id, query_id)
        self.assertFalse(result.error)
        self.assertTrue(result.complete)
        self.assertEqual(result.results, [[2]])

    def test_async_query_client_errors(self):
        query = "SELECT WOW SUCH DATA FROM NOWHERE THIS WILL CERTAINLY WORK"
        team_id = 2
        self.assertRaises(
            ServerException,
            client.enqueue_execute_with_progress,
            **{"team_id": team_id, "query": query, "bypass_celery": True},
        )
        try:
            query_id = client.enqueue_execute_with_progress(team_id, query, bypass_celery=True)
        except Exception:
            pass

        result = client.get_status_or_results(team_id, query_id)
        self.assertTrue(result.error)
        self.assertRegex(result.error_message, "Code: 62.\nDB::Exception: Syntax error:")

    def test_async_query_client_does_not_leak(self):
        query = "SELECT 1+1"
        team_id = 2
        wrong_team = 5
        query_id = client.enqueue_execute_with_progress(team_id, query, bypass_celery=True)
        result = client.get_status_or_results(wrong_team, query_id)
        self.assertTrue(result.error)
        self.assertEqual(result.error_message, "Requesting team is not executing team")

    @patch("posthog.clickhouse.client.execute_async.enqueue_clickhouse_execute_with_progress")
    def test_async_query_client_is_lazy(self, execute_sync_mock):
        query = "SELECT 4 + 4"
        team_id = 2
        client.enqueue_execute_with_progress(team_id, query, bypass_celery=True)

        # Try the same query again
        client.enqueue_execute_with_progress(team_id, query, bypass_celery=True)

        # Try the same query again (for good measure!)
        client.enqueue_execute_with_progress(team_id, query, bypass_celery=True)

        # Assert that we only called clickhouse once
        execute_sync_mock.assert_called_once()

    @patch("posthog.clickhouse.client.execute_async.enqueue_clickhouse_execute_with_progress")
    def test_async_query_client_is_lazy_but_not_too_lazy(self, execute_sync_mock):
        query = "SELECT 8 + 8"
        team_id = 2
        client.enqueue_execute_with_progress(team_id, query, bypass_celery=True)

        # Try the same query again, but with force
        client.enqueue_execute_with_progress(team_id, query, bypass_celery=True, force=True)

        # Try the same query again (for good measure!)
        client.enqueue_execute_with_progress(team_id, query, bypass_celery=True)

        # Assert that we called clickhouse twice
        self.assertEqual(execute_sync_mock.call_count, 2)

    @patch("posthog.clickhouse.client.execute_async.enqueue_clickhouse_execute_with_progress")
    def test_async_query_client_manual_query_uuid(self, execute_sync_mock):
        # This is a unique test because technically in the test pattern `SELECT 8 + 8` is already
        # in redis. This tests to make sure it is treated as a unique run of that query
        query = "SELECT 8 + 8"
        team_id = 2
        query_id = "I'm so unique"
        client.enqueue_execute_with_progress(team_id, query, query_id=query_id, bypass_celery=True)

        # Try the same query again, but with force
        client.enqueue_execute_with_progress(team_id, query, query_id=query_id, bypass_celery=True, force=True)

        # Try the same query again (for good measure!)
        client.enqueue_execute_with_progress(team_id, query, query_id=query_id, bypass_celery=True)

        # Assert that we called clickhouse twice
        self.assertEqual(execute_sync_mock.call_count, 2)

    def test_client_strips_comments_from_request(self):
        """
        To ensure we can easily copy queries from `system.query_log` in e.g.
        Metabase, we strip comments from the query we send. Metabase doesn't
        display multilined output.

        See https://github.com/metabase/metabase/issues/14253

        Note I'm not really testing much complexity, I trust that those will
        come out as failures in other tests.
        """
        from posthog.clickhouse.query_tagging import tag_queries

        # First add in the request information that should be added to the sql.
        # We check this to make sure it is not removed by the comment stripping
        with self.capture_select_queries() as sqls:
            tag_queries(kind="request", id="1")
            sync_execute(
                query="""
                    -- this request returns 1
                    SELECT 1
                """
            )
            self.assertEqual(len(sqls), 1)
            first_query = sqls[0]
            self.assertIn(f"SELECT 1", first_query)
            self.assertNotIn("this request returns", first_query)

            # Make sure it still includes the "annotation" comment that includes
            # request routing information for debugging purposes
            self.assertIn("/* request:1 */", first_query)
