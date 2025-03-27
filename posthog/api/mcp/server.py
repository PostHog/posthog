from mcp.server import Server
from mcp.types import Resource

mcp_server = Server("posthog")


@mcp_server.list_resources()
async def list_resources():
    return [Resource(uri="test", name="test")]
