from typing import Any

from .base import ToolFormatter
from .models import Tool


class AnthropicToolFormatter(ToolFormatter):
    """Anthropic tool format: {"name": ..., "description": ..., "input_schema": ...}"""

    def can_parse(self, tool_data: dict[str, Any]) -> bool:
        return "name" in tool_data and "input_schema" in tool_data

    def parse(self, tools_data: list[dict[str, Any]]) -> list[Tool]:
        return [
            Tool(
                name=tool_data["name"],
                description=tool_data.get("description", ""),
                parameters=tool_data["input_schema"],
            )
            for tool_data in tools_data
        ]

    def serialize(self, tools: list[Tool]) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in tools
        ]
