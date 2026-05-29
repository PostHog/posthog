from typing import Any

from .base import ToolFormatter
from .models import Tool


class OpenAIToolFormatter(ToolFormatter):
    """OpenAI tool format: {"type": "function", "function": {...}}"""

    def can_parse(self, tool_data: dict[str, Any]) -> bool:
        return (
            tool_data.get("type") == "function"
            and "function" in tool_data
            and "name" in tool_data["function"]
            and "parameters" in tool_data["function"]
        )

    def parse(self, tools_data: list[dict[str, Any]]) -> list[Tool]:
        return [
            Tool(
                name=tool_data["function"]["name"],
                description=tool_data["function"].get("description", ""),
                parameters=tool_data["function"]["parameters"],
            )
            for tool_data in tools_data
        ]

    def serialize(self, tools: list[Tool]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in tools
        ]
