import json
import uuid

import pytest

from django.conf import settings

import aiohttp
import pydantic
import pytest_asyncio

from products.batch_exports.backend.tests.temporal.destinations.workflows.utils import RequestData


class ClickHouseEventSchema(pydantic.BaseModel):
    """Matches the Zod schema in nodejs/src/cdp/services/batch-export-hog-function.service.ts.

    Not sure if there is a better way to sync these two schemas?
    """

    uuid: str
    event: str
    team_id: int
    distinct_id: str
    person_id: str | None = None
    timestamp: str
    captured_at: str | None = None
    properties: str | None = None
    elements_chain: str = ""
    person_properties: str | None = None


class BatchExportRequestSchema(pydantic.BaseModel):
    clickhouse_event: ClickHouseEventSchema
    invocation_id: str | None = None


@pytest.fixture
def events_table() -> str:
    return "sharded_events"


@pytest.fixture()
def hog_function_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def path() -> str:
    return "/api/projects/{team_id}/hog_functions/{hog_function_id}/batch_export_invocations"


class Handler:
    """Handler for the test server.

    The handler can be configured to return an error response once with the code given
    by ``error``.

    Validates request bodies against the CDP API's expected schema (Zod) using a
    matching Pydantic model.

    ``data`` and ``error_data`` can be used to verify request data in tests. They will
    contain a three item tuple: (team_id, hog_function_id, body). ``error_data`` is only
    populated when an error response is returned, and ``data`` is only populated on
    successful responses.
    """

    def __init__(self, error: int | None = None):
        self.data: list[RequestData] = []

        self.error_data: list[RequestData] = []
        self.error = error
        self.has_errored_once = False

    def __call__(self, request):
        return self.handle(request)

    async def handle(self, request):
        provided_secret = request.headers.get("X-Internal-Api-Secret", "")
        if provided_secret != settings.INTERNAL_API_SECRET:
            return aiohttp.web.Response(status=401, text="Unauthorized: Missing or invalid authentication header")

        team_id = request.match_info["team_id"]
        hog_function_id = request.match_info["hog_function_id"]
        body = await request.read()

        try:
            BatchExportRequestSchema.model_validate(json.loads(body))
        except pydantic.ValidationError as e:
            return aiohttp.web.Response(
                status=400,
                text=json.dumps({"errors": [f"Invalid request body: {e}"]}),
                content_type="application/json",
            )

        if self.error is not None and not self.has_errored_once:
            self.has_errored_once = True
            self.error_data.append(RequestData(team_id, hog_function_id, body))
            return aiohttp.web.Response(status=self.error, text="error")

        self.data.append(RequestData(team_id, hog_function_id, body))
        return aiohttp.web.Response(status=200, text="ok")


@pytest.fixture
def error(request) -> int | None:
    """Parameterize this fixture with an error status code for the request to fail."""
    try:
        return request.param
    except AttributeError:
        return None


@pytest.fixture
def handler(error):
    return Handler(error=error)


@pytest_asyncio.fixture
async def server(aiohttp_server, path, handler):
    """Test server provided by aiohttp."""
    app = aiohttp.web.Application()
    app.add_routes(
        [
            aiohttp.web.post(path, handler),
        ]
    )

    server = await aiohttp_server(app)

    return server
