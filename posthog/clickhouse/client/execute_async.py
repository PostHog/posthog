import datetime
import uuid
from typing import TYPE_CHECKING, Optional

import orjson as json
import structlog
from prometheus_client import Histogram
from pydantic import BaseModel
from rest_framework.exceptions import APIException, NotFound

from posthog import celery, redis
from posthog.clickhouse.client.async_task_chain import add_task_to_on_commit
from posthog.clickhouse.query_tagging import tag_queries
from posthog.errors import CHQueryErrorTooManySimultaneousQueries, ExposedCHQueryError
from posthog.hogql.constants import LimitContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.renderers import SafeJSONRenderer
from posthog.schema import ClickhouseQueryProgress, QueryStatus
from posthog.tasks.tasks import process_query_task
from posthog.exceptions_capture import capture_exception

if TYPE_CHECKING:
    from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)

CUSTOM_BUCKETS = (0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 7.5, 10.0, 20, 30, 60, 120, 300, 600, float("inf"))

QUERY_WAIT_TIME = Histogram(
    "query_wait_time_seconds",
    "Time from query creation to pick-up",
    labelnames=["team", "mode"],
    buckets=Histogram.DEFAULT_BUCKETS[2:-1] + (20, 30, 60, 120, 300, 600, float("inf")),
)

QUERY_PROCESS_TIME = Histogram(
    "query_process_time_seconds", "Time from query pick-up to result", labelnames=["team"], buckets=CUSTOM_BUCKETS
)


class QueryNotFoundError(NotFound):
    pass


class QueryRetrievalError(Exception):
    pass


class QueryStatusManager:
    STATUS_TTL_SECONDS = 60 * 20  # 20 minutes
    KEY_PREFIX_ASYNC_RESULTS = "query_async"

    def __init__(self, query_id: str, team_id: int):
        self.redis_client = redis.get_client()
        self.query_id = query_id
        self.team_id = team_id

    @property
    def results_key(self) -> str:
        return f"{self.KEY_PREFIX_ASYNC_RESULTS}:{self.team_id}:{self.query_id}"

    @property
    def clickhouse_query_status_key(self) -> str:
        return f"{self.KEY_PREFIX_ASYNC_RESULTS}:{self.team_id}:{self.query_id}:status"

    def store_query_status(self, query_status: QueryStatus):
        value = SafeJSONRenderer().render(query_status.model_dump(exclude={"clickhouse_query_progress"}))
        query_status.expiration_time = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            seconds=self.STATUS_TTL_SECONDS
        )
        self.redis_client.set(self.results_key, value, exat=int(query_status.expiration_time.timestamp()))

    def _store_clickhouse_query_progress_dict(self, query_progress_dict):
        value = json.dumps(query_progress_dict)
        self.redis_client.set(self.clickhouse_query_status_key, value, ex=self.STATUS_TTL_SECONDS)

    def _get_results(self):
        try:
            byte_results = self.redis_client.get(self.results_key)
        except Exception as e:
            raise QueryRetrievalError(f"Error retrieving query {self.query_id} for team {self.team_id}") from e

        return byte_results

    def _get_clickhouse_query_progress_dict(self):
        try:
            byte_results = self.redis_client.get(self.clickhouse_query_status_key)
        except Exception:
            # Don't fail because of progress checking
            return {}

        if byte_results is None:
            return {}

        return json.loads(byte_results)

    def update_clickhouse_query_progresses(self, clickhouse_query_progresses):
        clickhouse_query_progress_dict = self._get_clickhouse_query_progress_dict()
        for clickhouse_query_progress in clickhouse_query_progresses:
            clickhouse_query_progress_dict[clickhouse_query_progress["query_id"]] = clickhouse_query_progress
        self._store_clickhouse_query_progress_dict(clickhouse_query_progress_dict)

    def has_results(self) -> bool:
        return self.redis_client.exists(self.results_key) == 1

    def get_clickhouse_progresses(self) -> Optional[ClickhouseQueryProgress]:
        try:
            clickhouse_query_progress_dict = self._get_clickhouse_query_progress_dict()
            query_progress = {
                "bytes_read": 0,
                "rows_read": 0,
                "estimated_rows_total": 0,
                "time_elapsed": 0,
                "active_cpu_time": 0,
            }
            for single_query_progress in clickhouse_query_progress_dict.values():
                for k in query_progress.keys():
                    query_progress[k] += single_query_progress[k]
            return ClickhouseQueryProgress(**query_progress)
        except Exception as e:
            logger.exception("Clickhouse Status Check Failed", error=e)
            return None

    def get_query_status(self, show_progress: bool = False) -> QueryStatus:
        byte_results = self._get_results()

        if not byte_results:
            raise QueryNotFoundError(f"Query {self.query_id} not found for team {self.team_id}")

        query_status = QueryStatus(**json.loads(byte_results))

        if show_progress and not query_status.complete:
            query_status.query_progress = self.get_clickhouse_progresses()

        return query_status

    def delete_query_status(self) -> None:
        logger.info("Deleting redis query key %s", self.results_key)
        self.redis_client.delete(self.results_key)
        self.redis_client.delete(self.clickhouse_query_status_key)


def execute_process_query(
    team_id: int,
    user_id: Optional[int],
    query_id: str,
    query_json: dict,
    limit_context: Optional[LimitContext],
    is_query_service: bool = False,
):
    tag_queries(client_query_id=query_id, team_id=team_id, user_id=user_id)
    manager = QueryStatusManager(query_id, team_id)

    from posthog.api.services.query import ExecutionMode, process_query_dict
    from posthog.models import Team
    from posthog.models.user import User

    team = Team.objects.get(pk=team_id)
    is_staff_user = False

    user = None
    if user_id:
        user = User.objects.only("email", "is_staff").get(pk=user_id)
        is_staff_user = user.is_staff

    query_status = manager.get_query_status()

    if query_status.complete:
        return

    query_status.pickup_time = datetime.datetime.now(datetime.UTC)
    manager.store_query_status(query_status)

    query_status.error = True  # Assume error in case nothing below ends up working
    query_status.complete = True

    trigger = "chained" if "chained" in (query_status.labels or []) else ""
    if trigger == "chained":
        tag_queries(trigger="chaining")

    if query_status.start_time:
        wait_duration = (query_status.pickup_time - query_status.start_time) / datetime.timedelta(seconds=1)
        QUERY_WAIT_TIME.labels(team=team_id, mode=trigger).observe(wait_duration)

    try:
        results = process_query_dict(
            team=team,
            query_json=query_json,
            limit_context=limit_context,
            execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            insight_id=query_status.insight_id,
            dashboard_id=query_status.dashboard_id,
            user=user,
            is_query_service=is_query_service,
        )
        if isinstance(results, BaseModel):
            results = results.model_dump(by_alias=True)
        logger.info("Got results for team %s query %s", team_id, query_id)
        query_status.error = False
        query_status.results = results
        process_duration = (datetime.datetime.now(datetime.UTC) - query_status.pickup_time) / datetime.timedelta(
            seconds=1
        )
        QUERY_PROCESS_TIME.labels(team=team_id).observe(process_duration)
    except CHQueryErrorTooManySimultaneousQueries:
        raise
    except Exception as err:
        query_status.results = None  # Clear results in case they are faulty
        if isinstance(err, APIException | ExposedHogQLError | ExposedCHQueryError) or is_staff_user:
            # We can only expose the error message if it's a known safe error OR if the user is PostHog staff
            query_status.error_message = str(err)
        logger.exception("Error processing query async", team_id=team_id, query_id=query_id, exc_info=True)
        capture_exception(err)
        # Do not raise here, the task itself did its job and we cannot recover
    finally:
        query_status.end_time = datetime.datetime.now(datetime.UTC)
        manager.store_query_status(query_status)


def enqueue_process_query_task(
    team: "Team",
    user_id: Optional[int],
    query_json: dict,
    *,
    insight_id: Optional[int] = None,
    dashboard_id: Optional[int] = None,
    query_id: Optional[str] = None,
    # Attention: This is to pierce through the _manager_ cache, query runner will always refresh
    refresh_requested: bool = False,
    force: bool = False,
    _test_only_bypass_celery: bool = False,
    is_query_service: bool = False,
) -> QueryStatus:
    if not query_id:
        query_id = uuid.uuid4().hex

    manager = QueryStatusManager(query_id, team.id)

    if force:
        cancel_query(team.id, query_id)

    if manager.has_results() and not refresh_requested:
        # If we've seen this query before return and don't resubmit it.
        return manager.get_query_status()

    # Immediately set status, so we don't have race with celery
    query_status = QueryStatus(
        id=query_id,
        team_id=team.id,
        start_time=datetime.datetime.now(datetime.UTC),
        insight_id=insight_id,
        dashboard_id=dashboard_id,
    )
    manager.store_query_status(query_status)

    task_signature = process_query_task.si(
        team.id, user_id, query_id, query_json, is_query_service, LimitContext.QUERY_ASYNC
    )

    if _test_only_bypass_celery:
        task_signature()
    else:
        add_task_to_on_commit(task_signature=task_signature, manager=manager, query_status=query_status)

    return query_status


def get_query_status(team_id: int, query_id: str, show_progress: bool = False) -> QueryStatus:
    """
    Abstracts away the manager for any caller and returns a QueryStatus object
    """
    manager = QueryStatusManager(query_id, team_id)
    return manager.get_query_status(show_progress=show_progress)


def cancel_query(team_id: int, query_id: str, dequeue_only: bool = False) -> str:
    """
    Cancel a query.
    First tries to see if the query is queued in celery and revokes it.
    If the query is not queued, it will be cancelled on clickhouse.

    If dequeue_only is True, only tries to revoke the task, not cancel the query on clickhouse.
    Useful as we don't want to overwhelm clickhouse with KILL queries.
    """
    manager = QueryStatusManager(query_id, team_id)
    message = "Query task revoked"

    try:
        query_status = manager.get_query_status()

        if query_status.complete:
            return "Query already complete"

        if query_status.task_id:
            logger.info("Got task id %s, attempting to revoke", query_status.task_id)
            celery.app.control.revoke(query_status.task_id)

            logger.info("Revoked task id %s", query_status.task_id)
    except QueryNotFoundError:
        # Continue, to attempt to cancel the query even if it's not a task
        pass

    if dequeue_only:
        message = "Only tried to dequeue, not cancelling query on clickhouse"
    else:
        from posthog.clickhouse.cancel import cancel_query_on_cluster

        cancel_query_on_cluster(team_id, query_id)
        message = "Cancelled query on clickhouse"

    manager.delete_query_status()

    return message
