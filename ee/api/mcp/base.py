from mcp_server.djangomcp import DjangoMCP

mcp = DjangoMCP(name="PostHog MCP", instructions="Query analytics, errors and manage feature flags.")


@mcp.tool()
def add(a: int, b: int) -> int:
    return a + b
