import datetime

import orjson as json
from typing import TYPE_CHECKING, Optional
import uuid

from pydantic import BaseModel
import sentry_sdk
import structlog
from prometheus_client import Histogram
from rest_framework.exceptions import NotFound

from posthog import celery, redis
from posthog.clickhouse.client.async_task_chain import add_task_to_chain
from posthog.clickhouse.query_tagging import tag_queries
from posthog.errors import ExposedCHQueryError
from posthog.hogql.constants import LimitContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.renderers import SafeJSONRenderer
from posthog.schema import QueryStatus
from posthog.schema import ClickhouseQueryProgress
from posthog.tasks.tasks import process_query_task

if TYPE_CHECKING:
    from posthog.models.team.team import Team
    from posthog.models.user import User

logger = structlog.get_logger(__name__)

QUERY_WAIT_TIME = Histogram("query_wait_time_seconds", "Time from query creation to pick-up", labelnames=["team"])
QUERY_PROCESS_TIME = Histogram("query_process_time_seconds", "Time from query pick-up to result", labelnames=["team"])


class QueryNotFoundError(NotFound):
    pass


class QueryRetrievalError(Exception):
    pass


class QueryStatusManager:
    STATUS_TTL_SECONDS = 600  # 10 minutes
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
        self.redis_client.set(self.results_key, value, ex=self.STATUS_TTL_SECONDS)

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

        return json.loads(byte_results) if byte_results is not None else {}

    def update_clickhouse_query_progress(self, initial_query_id, clickhouse_query_progress):
        clickhouse_query_progress_dict = self._get_clickhouse_query_progress_dict()
        clickhouse_query_progress_dict[initial_query_id] = clickhouse_query_progress
        self._store_clickhouse_query_progress_dict(clickhouse_query_progress_dict)

    def has_results(self):
        return self._get_results() is not None

    def get_query_status(self, show_progress=False) -> QueryStatus:
        byte_results = self._get_results()

        if not byte_results:
            raise QueryNotFoundError(f"Query {self.query_id} not found for team {self.team_id}")

        query_status = QueryStatus(**json.loads(byte_results))

        if show_progress and not query_status.complete:
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
                    query_progress["bytes_read"] += single_query_progress["bytes_read"]
                    query_progress["rows_read"] += single_query_progress["rows_read"]
                    query_progress["estimated_rows_total"] += single_query_progress["estimated_rows_total"]
                    query_progress["time_elapsed"] += single_query_progress["time_elapsed"]
                    query_progress["active_cpu_time"] += single_query_progress["active_cpu_time"]
                query_status.query_progress = ClickhouseQueryProgress(**query_progress)
            except Exception as e:
                logger.error("Clickhouse Status Check Failed", error=e)
                pass

        return query_status

    def delete_query_status(self):
        logger.info("Deleting redis query key %s", self.results_key)
        self.redis_client.delete(self.results_key)
        self.redis_client.delete(self.clickhouse_query_status_key)


def execute_process_query(
    team_id: int,
    user_id: Optional[int],
    query_id: str,
    query_json: dict,
    limit_context: Optional[LimitContext],
):
    manager = QueryStatusManager(query_id, team_id)

    from posthog.api.services.query import process_query_dict, ExecutionMode
    from posthog.models import Team
    from posthog.models.user import User

    team = Team.objects.get(pk=team_id)
    sentry_sdk.set_tag("team_id", team_id)

    if user_id:
        user = User.objects.get(pk=user_id)
        sentry_sdk.set_user({"email": user.email, "id": user_id, "username": user.email})

    query_status = manager.get_query_status()

    if query_status.complete or query_status.error:
        return

    query_status.error = True  # Assume error in case nothing below ends up working

    pickup_time = datetime.datetime.now(datetime.timezone.utc)
    if query_status.start_time:
        wait_duration = (pickup_time - query_status.start_time) / datetime.timedelta(seconds=1)
        QUERY_WAIT_TIME.labels(team=team_id).observe(wait_duration)

    try:
        tag_queries(client_query_id=query_id, team_id=team_id, user_id=user_id)
        results = process_query_dict(
            team=team,
            query_json=query_json,
            limit_context=limit_context,
            execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
        )
        if isinstance(results, BaseModel):
            results = results.model_dump(by_alias=True)
        logger.info("Got results for team %s query %s", team_id, query_id)
        query_status.complete = True
        query_status.error = False
        query_status.results = results
        query_status.end_time = datetime.datetime.now(datetime.timezone.utc)
        query_status.expiration_time = query_status.end_time + datetime.timedelta(seconds=manager.STATUS_TTL_SECONDS)
        process_duration = (query_status.end_time - pickup_time) / datetime.timedelta(seconds=1)
        QUERY_PROCESS_TIME.labels(team=team_id).observe(process_duration)
    except (ExposedHogQLError, ExposedCHQueryError) as err:  # We can expose the error to the user
        query_status.results = None  # Clear results in case they are faulty
        query_status.error_message = str(err)
        logger.error("Error processing query for team %s query %s: %s", team_id, query_id, err)
        raise err
    except Exception as err:  # We cannot reveal anything about the error
        query_status.results = None  # Clear results in case they are faulty
        logger.error("Error processing query for team %s query %s: %s", team_id, query_id, err)
        raise err
    finally:
        manager.store_query_status(query_status)


def enqueue_process_query_task(
    team: "Team",
    user: Optional["User"],
    query_json: dict,
    query_id: Optional[str] = None,
    # Attention: This is to pierce through the _manager_ cache, query runner will always refresh
    refresh_requested: bool = False,
    force: bool = False,
    _test_only_bypass_celery: bool = False,
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
    query_status = QueryStatus(id=query_id, team_id=team.id, start_time=datetime.datetime.now(datetime.timezone.utc))
    manager.store_query_status(query_status)

    task_signature = process_query_task.si(
        team.id, user.id if user else None, query_id, query_json, LimitContext.QUERY_ASYNC
    )

    if _test_only_bypass_celery:
        task_signature()
    else:
        add_task_to_chain(task_signature=task_signature, manager=manager, query_status=query_status)

    return query_status


def get_query_status(team_id, query_id, show_progress=False) -> QueryStatus:
    """
    Abstracts away the manager for any caller and returns a QueryStatus object
    """
    manager = QueryStatusManager(query_id, team_id)
    return manager.get_query_status(show_progress=show_progress)


def cancel_query(team_id, query_id):
    manager = QueryStatusManager(query_id, team_id)

    try:
        query_status = manager.get_query_status()

        if query_status.task_id:
            logger.info("Got task id %s, attempting to revoke", query_status.task_id)
            celery.app.control.revoke(query_status.task_id, terminate=True)

            logger.info("Revoked task id %s", query_status.task_id)
    except QueryNotFoundError:
        # Continue, to attempt to cancel the query even if it's not a task
        pass

    from posthog.clickhouse.cancel import cancel_query_on_cluster

    cancel_query_on_cluster(team_id, query_id)

    manager.delete_query_status()

    return True
