from posthog.api.services.query import process_query_model
from posthog.hogql_queries.query_runner import ExecutionMode, execution_mode_from_refresh
from posthog.clickhouse.query_tagging import tag_queries
from pydantic import BaseModel
from posthog.errors import ExposedCHQueryError
from posthog.hogql.errors import ExposedHogQLError
from sentry_sdk import capture_exception
from asgiref.sync import sync_to_async

from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle, HogQLQueryThrottle
from posthog.api.websocket import BaseWebsocketConsumer
import json
import uuid
from typing import Generic, TypeVar

T = TypeVar("T")


class Response(BaseModel, Generic[T]):
    status: int
    result: T
    client_query_id: str


def _query(user, query, execution_mode, query_id):
    return process_query_model(
        user.team,
        query,
        execution_mode=execution_mode,
        query_id=query_id,
        user=user,
    )


class QueryConsumer(BaseWebsocketConsumer):
    def get_throttles(self, data):
        if query := data.get("query"):
            if isinstance(query, dict) and query.get("kind") == "HogQLQuery":
                return [HogQLQueryThrottle()]
        return [ClickHouseBurstRateThrottle(), ClickHouseSustainedRateThrottle()]

    async def connect(self):
        # Accept the WebSocket connection
        if not await self.check_authentication():
            return
        await self.accept()

    async def disconnect(self, close_code):
        # Handle WebSocket disconnection (if needed)
        pass

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            if not await self.check_throttling(data):
                return

            # Extract and process the query
            client_query_id = data.get("client_query_id") or uuid.uuid4().hex
            execution_mode = execution_mode_from_refresh(data.get("refresh"))
            response_status = 200

            # Add tagging if needed
            # self._tag_client_query_id(client_query_id)

            # websockets we always want to "block"
            if execution_mode in [
                ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE,
                ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS,
                ExecutionMode.EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE,
            ]:
                execution_mode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
            if execution_mode in [ExecutionMode.CALCULATE_ASYNC_ALWAYS]:
                execution_mode = ExecutionMode.CALCULATE_BLOCKING_ALWAYS

            tag_queries(query=data["query"])

            # Execute query asynchronously
            result = await sync_to_async(_query)(
                self.scope["user"],
                data["query"],
                execution_mode=execution_mode,
                query_id=client_query_id,
            )

            # Send response back to the client
            response: Response = Response(status=response_status, result=result, client_query_id=client_query_id)
            await self.send(response.model_dump_json(by_alias=True))

        except (ExposedHogQLError, ExposedCHQueryError) as e:
            # Handle validation errors
            await self.send(
                json.dumps(
                    {
                        "status": 400,
                        "error": str(e),
                        "client_query_id": client_query_id,
                        "code": getattr(e, "code_name", None),
                    }
                )
            )

        except Exception as e:
            # Handle unexpected errors
            capture_exception(e)
            await self.send(
                json.dumps(
                    {
                        "status": 500,
                        "error": "Internal server error",
                        "client_query_id": client_query_id,
                        "exception": str(e),
                    }
                )
            )
