from mcp_server.djangomcp import DjangoMCP

mcp = DjangoMCP(name="PostHog MCP", instructions="Query analytics, errors and manage feature flags.", stateless=True)


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers together."""
    return a + b
