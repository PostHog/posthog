import datetime

import fakeredis
from django.test import TestCase
from freezegun import freeze_time

from ee.clickhouse import client
from ee.clickhouse.client import CACHE_TTL, _deserialize, _key_hash, cache_sync_execute, sync_execute
from ee.clickhouse.util import ClickhouseTestMixin


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
