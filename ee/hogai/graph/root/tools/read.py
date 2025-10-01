from typing import Any, Literal

from pydantic import BaseModel

from ee.hogai.tool import MaxTool

READ_DATA_PROMPT = """
Use this tool to read user data created in PostHog. This tool returns data that the user manually creates in PostHog.

# Data warehouse schema

Returns the SQL ClickHouse schema for the user's data warehouse.
You MUST use this tool:
- Working with SQL.
- The request is about data warehouse, connected data sources, etc.

# Billing information

If the user asks about billing, their subscription, their usage, or their spending, use the this tool with the "billing_info" kind to retrieve the billing information.
You can use the information retrieved to check which PostHog products and add-ons the user has activated, how much they are spending, their usage history across all products in the last 30 days, as well as trials, spending limits, billing period, and more.
If the user wants to reduce their spending, always call this tool to get suggestions on how to do so.
If an insight shows zero data, it could mean either the query is looking at the wrong data or there was a temporary data collection issue. You can investigate potential dips in usage/captured data using the billing tool.
""".strip()

ReadDataKind = Literal["datawarehouse_schema", "billing_info"]


class ReadDataToolArgs(BaseModel):
    kind: ReadDataKind


class ReadDataTool(MaxTool):
    name: Literal["ReadData"] = "ReadData"
    description: str = READ_DATA_PROMPT
    thinking_message: str = "Reading your PostHog data"
    root_system_prompt_template: str = "Reads user data created in PostHog (data warehouse schema, billing information)"
    args_schema: type[BaseModel] = ReadDataToolArgs
    show_tool_call_message: bool = False

    async def _arun_impl(self, kind: ReadDataKind) -> tuple[str, Any]:
        return "ReadData tool executed", ReadDataToolArgs(kind=kind)
