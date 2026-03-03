import uuid

import pytest

import aiohttp
import pytest_asyncio

from products.batch_exports.backend.tests.temporal.destinations.workflows.utils import RequestData


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
    def __init__(self):
        self.data: list[RequestData] = []

    def __call__(self, request):
        return self.handle(request)

    async def handle(self, request):
        team_id = request.match_info["team_id"]
        hog_function_id = request.match_info["hog_function_id"]
        body = await request.read()
        self.data.append(RequestData(team_id, hog_function_id, body))
        return aiohttp.web.Response(status=200, text="ok")


@pytest.fixture
def handler():
    return Handler()


@pytest_asyncio.fixture
async def server(aiohttp_server, path, handler):
    app = aiohttp.web.Application()
    app.add_routes([aiohttp.web.post(path, handler)])

    server = await aiohttp_server(app)

    return server
