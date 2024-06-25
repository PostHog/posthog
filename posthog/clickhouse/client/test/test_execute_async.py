import json
from typing import Any

from posthog.clickhouse.client.async_task_chain import task_chain_context
from posthog.clickhouse.client.connection import Workload
import uuid

from django.test import TestCase, SimpleTestCase
from django.db import transaction

from posthog.clickhouse.client import execute_async as client
from posthog.client import sync_execute
from posthog.hogql.errors import ExposedHogQLError
from posthog.models import Organization, Team
from posthog.models.user import User
from posthog.redis import get_client
from posthog.schema import QueryStatus, ClickhouseQueryProgress
from posthog.test.base import ClickhouseTestMixin, snapshot_clickhouse_queries
from unittest.mock import patch, MagicMock
from posthog.clickhouse.client.execute_async import (
    QueryStatusManager,
    execute_process_query,
    QueryNotFoundError,
)


def build_query(sql):
    return {
        "kind": "HogQLQuery",
        "query": sql,
    }


ZERO_PROGRESS = {
    "bytes_read": 0,
    "rows_read": 0,
    "estimated_rows_total": 0,
    "time_elapsed": 0,
    "active_cpu_time": 0,
}


class TestQueryStatusManager(SimpleTestCase):
    def setUp(self):
        super().setUp()
        get_client().flushall()
        self.query_id = "550e8400-e29b-41d4-a716-446655440000"
        self.team_id = 12345
        self.query_status = QueryStatus(id=self.query_id, team_id=self.team_id)
        self.manager = QueryStatusManager(self.query_id, self.team_id)

    def test_is_empty(self):
        self.assertRaises(QueryNotFoundError, lambda: self.manager.get_query_status(True))

    def test_no_status(self):
        self.manager.store_query_status(self.query_status)
        self.query_status.query_progress = ClickhouseQueryProgress(**ZERO_PROGRESS)
        self.assertEqual(self.manager.get_query_status(True), self.query_status)

    def test_store_clickhouse_query_progress(self):
        query_status = {f"{self.team_id}_{self.query_id}_1": {"progress": 1234}}
        self.manager._store_clickhouse_query_progress_dict(query_status)
        self.assertEqual(self.manager._get_clickhouse_query_progress_dict(), query_status)

    def test_bad_progress(self):
        self.manager.store_query_status(self.query_status)
        query_status = {f"{self.team_id}_{self.query_id}_1": {"progress": "a"}}
        self.manager._store_clickhouse_query_progress_dict(query_status)
        self.assertEqual(self.manager.get_query_status(True), self.query_status)

    def test_update_clickhouse_query_progress(self):
        self.manager.store_query_status(self.query_status)

        query_id_1 = f"{self.team_id}_{self.query_id}_1"
        query_id_2 = f"{self.team_id}_{self.query_id}_2"
        query_id_3 = f"{self.team_id}_{self.query_id}_3"
        query_progress_dict = {
            query_id_1: {**ZERO_PROGRESS, "bytes_read": 1},
            query_id_2: {**ZERO_PROGRESS, "bytes_read": 2},
        }

        self.manager._store_clickhouse_query_progress_dict(query_progress_dict)
        self.manager.update_clickhouse_query_progress(
            query_id_2,
            {**ZERO_PROGRESS, "bytes_read": 10},
        )
        self.manager.update_clickhouse_query_progress(
            query_id_3,
            {**ZERO_PROGRESS, "bytes_read": 20},
        )

        self.query_status.query_progress = ClickhouseQueryProgress(**{**ZERO_PROGRESS, "bytes_read": 31})

        self.assertEqual(self.manager.get_query_status(show_progress=True), self.query_status)


class TestExecuteProcessQuery(TestCase):
    def setUp(self):
        self.user = User.objects.create(email="test@posthog.com")
        self.organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=self.organization)
        self.query_id = "test_query_id"
        self.query_json = {}
        self.limit_context = None
        self.refresh_requested = False
        self.manager = QueryStatusManager(self.query_id, self.team.id)

    @patch("posthog.clickhouse.client.execute_async.redis.get_client")
    @patch("posthog.api.services.query.process_query_dict")
    def test_execute_process_query(self, mock_process_query_dict, mock_redis_client):
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(
            {"id": self.query_id, "team_id": self.team.id, "complete": False, "error": False}
        ).encode()
        mock_redis_client.return_value = mock_redis

        mock_process_query_dict.return_value = [float("inf"), float("-inf"), float("nan"), 1.0, "👍"]

        execute_process_query(self.team.id, self.user.id, self.query_id, self.query_json, self.limit_context)

        mock_redis_client.assert_called_once()
        mock_process_query_dict.assert_called_once()

        # Assert that Redis set method was called with the correct arguments
        mock_redis.set.assert_called_once()
        args, kwargs = mock_redis.set.call_args
        args_loaded = json.loads(args[1])
        self.assertEqual(args_loaded["results"], [None, None, None, 1.0, "👍"])


class ClickhouseClientTestCase(TestCase, ClickhouseTestMixin):
    def setUp(self):
        self.user = User.objects.create(email="test@posthog.com", id=1337)
        self.organization: Organization = Organization.objects.create(name="test")
        self.team: Team = Team.objects.create(organization=self.organization)
        self.team_id: int = self.team.pk
        self.user_id: int = self.user.id

    @snapshot_clickhouse_queries
    def test_async_query_client(self):
        query = build_query("SELECT 1+1")
        query_id = client.enqueue_process_query_task(self.team, self.user, query, _test_only_bypass_celery=True).id
        result = client.get_query_status(self.team.id, query_id)
        self.assertFalse(result.error, result.error_message or "<no error message>")
        self.assertTrue(result.complete)
        assert result.results is not None
        self.assertEqual(result.results["results"], [[2]])

    def test_async_query_client_errors(self):
        query = build_query("SELECT WOW SUCH DATA FROM NOWHERE THIS WILL CERTAINLY WORK")
        self.assertRaises(
            ExposedHogQLError,
            client.enqueue_process_query_task,
            **{"team": self.team, "user": self.user, "query_json": query, "_test_only_bypass_celery": True},
        )
        query_id = uuid.uuid4().hex
        try:
            client.enqueue_process_query_task(
                self.team, self.user, query, query_id=query_id, _test_only_bypass_celery=True
            )
        except Exception:
            pass

        result = client.get_query_status(self.team.id, query_id)
        self.assertTrue(result.error)
        assert result.error_message
        self.assertRegex(result.error_message, "no viable alternative at input")

    def test_async_query_client_uuid(self):
        query = build_query("SELECT toUUID('00000000-0000-0000-0000-000000000000')")
        query_id = client.enqueue_process_query_task(self.team, self.user, query, _test_only_bypass_celery=True).id
        result = client.get_query_status(self.team.id, query_id)
        self.assertFalse(result.error, result.error_message or "<no error message>")
        self.assertTrue(result.complete)
        assert result.results is not None
        self.assertEqual(result.results["results"], [["00000000-0000-0000-0000-000000000000"]])

    def test_async_query_client_does_not_leak(self):
        query = build_query("SELECT 1+1")
        wrong_team = 5
        query_id = client.enqueue_process_query_task(self.team, self.user, query, _test_only_bypass_celery=True).id

        try:
            client.get_query_status(wrong_team, query_id)
        except Exception as e:
            self.assertEqual(str(e), f"Query {query_id} not found for team {wrong_team}")

    @patch("posthog.client.execute_process_query")
    def test_async_query_client_is_lazy(self, execute_process_query_mock):
        query = build_query("SELECT 4 + 4")
        query_id = uuid.uuid4().hex
        client.enqueue_process_query_task(self.team, self.user, query, query_id=query_id, _test_only_bypass_celery=True)

        # Try the same query again
        client.enqueue_process_query_task(self.team, self.user, query, query_id=query_id, _test_only_bypass_celery=True)

        # Try the same query again (for good measure!)
        client.enqueue_process_query_task(self.team, self.user, query, query_id=query_id, _test_only_bypass_celery=True)

        # Assert that we only called clickhouse once
        execute_process_query_mock.assert_called_once()

    @patch("posthog.client.execute_process_query")
    def test_async_query_client_is_lazy_but_not_too_lazy(self, execute_process_query_mock):
        query = build_query("SELECT 8 + 8")
        query_id = uuid.uuid4().hex
        client.enqueue_process_query_task(self.team, self.user, query, query_id=query_id, _test_only_bypass_celery=True)

        # Try the same query again, but with force
        client.enqueue_process_query_task(
            self.team, self.user, query, query_id=query_id, _test_only_bypass_celery=True, force=True
        )

        # Try the same query again (for good measure!)
        client.enqueue_process_query_task(self.team, self.user, query, query_id=query_id, _test_only_bypass_celery=True)

        # Assert that we called clickhouse twice
        self.assertEqual(execute_process_query_mock.call_count, 2)

    @patch("posthog.client.execute_process_query")
    def test_async_query_client_manual_query_uuid(self, execute_process_query_mock):
        # This is a unique test because technically in the test pattern `SELECT 8 + 8` is already
        # in redis. This tests to make sure it is treated as a unique run of that query
        query = build_query("SELECT 8 + 8")
        query_id = "I'm so unique"
        client.enqueue_process_query_task(self.team, self.user, query, query_id=query_id, _test_only_bypass_celery=True)

        # Try the same query again, but with force
        client.enqueue_process_query_task(
            self.team, self.user, query, query_id=query_id, _test_only_bypass_celery=True, force=True
        )

        # Try the same query again (for good measure!)
        client.enqueue_process_query_task(self.team, self.user, query, query_id=query_id, _test_only_bypass_celery=True)

        # Assert that we called clickhouse twice
        self.assertEqual(execute_process_query_mock.call_count, 2)

    @patch("posthog.client.execute_process_query")
    @patch("posthog.api.services.query.process_query_dict")
    def test_async_query_refreshes_if_requested(self, process_query_dict_mock, execute_process_query_mock):
        query = build_query("SELECT 8 + 8")
        query_id = "query_id"

        client.enqueue_process_query_task(
            self.team,
            self.user,
            query,
            query_id=query_id,
            _test_only_bypass_celery=True,
            refresh_requested=True,
        )

        self.assertEqual(process_query_dict_mock.call_count, 0)
        self.assertEqual(execute_process_query_mock.call_count, 1)

    @patch("posthog.clickhouse.client.async_task_chain.execute_task_chain")
    @patch("django.db.transaction.on_commit")
    def test_context_manager_exit(self, on_commit_mock, execute_task_chain_mock):
        mock_chain: list[Any] = []
        with patch("posthog.clickhouse.client.async_task_chain.get_task_chain", return_value=mock_chain):
            with transaction.atomic():
                with task_chain_context():
                    query1 = build_query("SELECT 8 + 8")
                    query_id1 = "I'm so unique"
                    client.enqueue_process_query_task(self.team, self.user, query1, query_id=query_id1)

                    query2 = build_query("SELECT 4 + 4")
                    query_id2 = "I'm so unique 2"
                    client.enqueue_process_query_task(self.team, self.user, query2, query_id=query_id2)

                on_commit_mock.assert_called_once()
                on_commit_callback = on_commit_mock.call_args[0][0]
                on_commit_callback()

        execute_task_chain_mock.assert_called_once()

        self.assertEqual(len(mock_chain), 2)

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
            tag_queries(kind="request", id="1", user_id=self.user_id)
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

    @patch("posthog.clickhouse.client.execute.get_pool")
    def test_offline_workload_if_personal_api_key(self, mock_get_pool):
        from posthog.clickhouse.query_tagging import tag_queries

        with self.capture_select_queries():
            tag_queries(kind="request", id="1", access_method="personal_api_key")
            sync_execute("select 1")

            self.assertEqual(mock_get_pool.call_args[0][0], Workload.OFFLINE)
