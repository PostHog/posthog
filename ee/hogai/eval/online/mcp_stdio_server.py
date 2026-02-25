"""Stdio MCP server that wraps PostHog's MCPTool registry for eval agents.

Usage:
    python -m ee.hogai.eval.online.mcp_stdio_server --team-id 2 --user-email test@posthog.com

The server exposes all registered MCP tools (execute_sql, read_taxonomy, etc.)
via the stdio transport, allowing Agents SDK to launch it as a subprocess.
"""

import json
import asyncio
import argparse

import django


def main():
    parser = argparse.ArgumentParser(description="PostHog eval MCP stdio server")
    parser.add_argument("--team-id", type=int, required=True)
    parser.add_argument("--user-email", type=str, required=True)
    args = parser.parse_args()

    django.setup()

    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    from posthog.models import Team, User

    from ee.hogai.mcp_tool import mcp_tool_registry
    from ee.hogai.tool_errors import MaxToolError

    team = Team.objects.get(pk=args.team_id)
    user = User.objects.get(email=args.user_email)

    server = Server("posthog-eval")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        tools: list[Tool] = []
        for name in mcp_tool_registry.get_names():
            tool_instance = mcp_tool_registry.get(name, team=team, user=user)
            if tool_instance is None:
                continue
            schema = tool_instance.args_schema.model_json_schema()
            tools.append(
                Tool(
                    name=name,
                    description=schema.get("description", name),
                    inputSchema=schema,
                )
            )
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        tool = mcp_tool_registry.get(name, team=team, user=user)
        if tool is None:
            return [
                TextContent(type="text", text=json.dumps({"success": False, "content": f"Tool '{name}' not found"}))
            ]

        try:
            validated_args = tool.args_schema.model_validate(arguments)
            content = await tool.execute(validated_args)
            return [TextContent(type="text", text=json.dumps({"success": True, "content": content}))]
        except MaxToolError as e:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"success": False, "content": f"Tool failed: {e.to_summary()}.{e.retry_hint}"}),
                )
            ]
        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"success": False, "content": f"Internal error: {type(e).__name__}: {e}"}),
                )
            ]

    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream)

    asyncio.run(run())


if __name__ == "__main__":
    main()
