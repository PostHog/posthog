import json
import uuid

from django.test import TestCase

from posthog.clickhouse.client import execute_async as client
from posthog.client import sync_execute
from posthog.hogql.errors import HogQLException
from posthog.models import Organization, Team
from posthog.test.base import ClickhouseTestMixin, snapshot_clickhouse_queries
from unittest.mock import patch, MagicMock
from posthog.clickhouse.client.execute_async import QueryStatusManager, execute_process_query


def build_query(sql):
    return {
        "kind": "HogQLQuery",
        "query": sql,
    }


class TestExecuteProcessQuery(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=self.organization)
        self.team_id = self.team.pk
        self.user_id = 1337
        self.query_id = "test_query_id"
        self.query_json = {}
        self.limit_context = None
        self.refresh_requested = False
        self.manager = QueryStatusManager(self.query_id, self.team_id)

    @patch("posthog.clickhouse.client.execute_async.redis.get_client")
    @patch("posthog.api.services.query.process_query")
    def test_execute_process_query(self, mock_process_query, mock_redis_client):
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(
            {"id": self.query_id, "team_id": self.team_id, "complete": False, "error": False}
        ).encode()
        mock_redis_client.return_value = mock_redis

        mock_process_query.return_value = [float("inf"), float("-inf"), float("nan"), 1.0, "👍"]

        execute_process_query(
            self.team_id, self.user_id, self.query_id, self.query_json, self.limit_context, self.refresh_requested
        )

        mock_redis_client.assert_called_once()
        mock_process_query.assert_called_once()

        # Assert that Redis set method was called with the correct arguments
        mock_redis.set.assert_called_once()
        args, kwargs = mock_redis.set.call_args
        args_loaded = json.loads(args[1])
        self.assertEqual(args_loaded["results"], [None, None, None, 1.0, "👍"])


class ClickhouseClientTestCase(TestCase, ClickhouseTestMixin):
    def setUp(self):
        self.organization: Organization = Organization.objects.create(name="test")
        self.team: Team = Team.objects.create(organization=self.organization)
        self.team_id: int = self.team.pk
        self.user_id: int = 2137

    @snapshot_clickhouse_queries
    def test_async_query_client(self):
        query = build_query("SELECT 1+1")
        team_id = self.team_id
        query_id = client.enqueue_process_query_task(team_id, self.user_id, query, _test_only_bypass_celery=True).id
        result = client.get_query_status(team_id, query_id)
        self.assertFalse(result.error, result.error_message or "<no error message>")
        self.assertTrue(result.complete)
        assert result.results is not None
        self.assertEqual(result.results["results"], [[2]])

    def test_async_query_client_errors(self):
        query = build_query("SELECT WOW SUCH DATA FROM NOWHERE THIS WILL CERTAINLY WORK")
        self.assertRaises(
            HogQLException,
            client.enqueue_process_query_task,
            **{"team_id": self.team_id, "user_id": self.user_id, "query_json": query, "_test_only_bypass_celery": True},
        )
        query_id = uuid.uuid4().hex
        try:
            client.enqueue_process_query_task(
                self.team_id, self.user_id, query, query_id=query_id, _test_only_bypass_celery=True
            )
        except Exception:
            pass

        result = client.get_query_status(self.team_id, query_id)
        self.assertTrue(result.error)
        assert result.error_message
        self.assertRegex(result.error_message, "Unknown table")

    def test_async_query_client_uuid(self):
        query = build_query("SELECT toUUID('00000000-0000-0000-0000-000000000000')")
        team_id = self.team_id
        query_id = client.enqueue_process_query_task(team_id, self.user_id, query, _test_only_bypass_celery=True).id
        result = client.get_query_status(team_id, query_id)
        self.assertFalse(result.error, result.error_message or "<no error message>")
        self.assertTrue(result.complete)
        assert result.results is not None
        self.assertEqual(result.results["results"], [["00000000-0000-0000-0000-000000000000"]])

    def test_async_query_client_does_not_leak(self):
        query = build_query("SELECT 1+1")
        team_id = self.team_id
        wrong_team = 5
        query_id = client.enqueue_process_query_task(team_id, self.user_id, query, _test_only_bypass_celery=True).id

        try:
            client.get_query_status(wrong_team, query_id)
        except Exception as e:
            self.assertEqual(str(e), f"Query {query_id} not found for team {wrong_team}")

    @patch("posthog.clickhouse.client.execute_async.process_query_task")
    def test_async_query_client_is_lazy(self, execute_sync_mock):
        query = build_query("SELECT 4 + 4")
        query_id = uuid.uuid4().hex
        team_id = self.team_id
        client.enqueue_process_query_task(
            team_id, self.user_id, query, query_id=query_id, _test_only_bypass_celery=True
        )

        # Try the same query again
        client.enqueue_process_query_task(
            team_id, self.user_id, query, query_id=query_id, _test_only_bypass_celery=True
        )

        # Try the same query again (for good measure!)
        client.enqueue_process_query_task(
            team_id, self.user_id, query, query_id=query_id, _test_only_bypass_celery=True
        )

        # Assert that we only called clickhouse once
        execute_sync_mock.assert_called_once()

    @patch("posthog.clickhouse.client.execute_async.process_query_task")
    def test_async_query_client_is_lazy_but_not_too_lazy(self, execute_sync_mock):
        query = build_query("SELECT 8 + 8")
        query_id = uuid.uuid4().hex
        team_id = self.team_id
        client.enqueue_process_query_task(
            team_id, self.user_id, query, query_id=query_id, _test_only_bypass_celery=True
        )

        # Try the same query again, but with force
        client.enqueue_process_query_task(
            team_id, self.user_id, query, query_id=query_id, _test_only_bypass_celery=True, force=True
        )

        # Try the same query again (for good measure!)
        client.enqueue_process_query_task(
            team_id, self.user_id, query, query_id=query_id, _test_only_bypass_celery=True
        )

        # Assert that we called clickhouse twice
        self.assertEqual(execute_sync_mock.call_count, 2)

    @patch("posthog.clickhouse.client.execute_async.process_query_task")
    def test_async_query_client_manual_query_uuid(self, execute_sync_mock):
        # This is a unique test because technically in the test pattern `SELECT 8 + 8` is already
        # in redis. This tests to make sure it is treated as a unique run of that query
        query = build_query("SELECT 8 + 8")
        team_id = self.team_id
        query_id = "I'm so unique"
        client.enqueue_process_query_task(
            team_id, self.user_id, query, query_id=query_id, _test_only_bypass_celery=True
        )

        # Try the same query again, but with force
        client.enqueue_process_query_task(
            team_id, self.user_id, query, query_id=query_id, _test_only_bypass_celery=True, force=True
        )

        # Try the same query again (for good measure!)
        client.enqueue_process_query_task(
            team_id, self.user_id, query, query_id=query_id, _test_only_bypass_celery=True
        )

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
            self.assertIn(f"/* user_id:{self.user_id} request:1 */", first_query)
