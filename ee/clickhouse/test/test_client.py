import datetime
from unittest.mock import patch

import fakeredis
from clickhouse_driver.errors import ServerException
from django.test import TestCase
from freezegun import freeze_time

from ee.clickhouse.util import ClickhouseTestMixin
from posthog import client
from posthog.client import CACHE_TTL, _deserialize, _key_hash, cache_sync_execute, sync_execute


class ClickhouseClientTestCase(TestCase, ClickhouseTestMixin):
    def setUp(self):
        self.redis_client = fakeredis.FakeStrictRedis()

    def test_caching_client(self):
        ts_start = datetime.datetime.now()
        query = "select 1"
        args = None
        res = cache_sync_execute(query, args=args, redis_client=self.redis_client)
        cache = self.redis_client.get(_key_hash(query, args=args))
        cache_res = _deserialize(cache)
        self.assertEqual(res, cache_res)
        ts_end = datetime.datetime.now()
        dur = (ts_end - ts_start).microseconds

        # second hits cache, should be faster
        ts_start = datetime.datetime.now()
        res_cached = cache_sync_execute(query, args=args, redis_client=self.redis_client)
        self.assertEqual(res, res_cached)
        ts_end = datetime.datetime.now()
        dur_cached = (ts_end - ts_start).microseconds

        self.assertLess(dur_cached, dur)

    def test_cache_eviction(self):
        query = "select 1"
        args = None
        start = datetime.datetime.fromisoformat("2020-01-01 12:00:00")
        with freeze_time(start.isoformat()):
            cache_sync_execute("select 1", args=args, redis_client=self.redis_client, ttl=CACHE_TTL)
        with freeze_time(start.isoformat()):
            exists = self.redis_client.exists(_key_hash(query, args=args))
            self.assertTrue(exists)
        with freeze_time(start + datetime.timedelta(seconds=CACHE_TTL + 10)):
            exists = self.redis_client.exists(_key_hash(query, args=args))
            self.assertFalse(exists)

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

    @patch("posthog.client.execute_with_progress")
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

    @patch("posthog.client.execute_with_progress")
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

    @patch("posthog.client.execute_with_progress")
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
        # First add in the request information that should be added to the sql.
        # We check this to make sure it is not removed by the comment stripping
        with self.capture_select_queries() as sqls:
            client._request_information = {"kind": "request", "id": "1"}
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
