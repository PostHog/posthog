from __future__ import annotations

from django.conf import settings

from pydantic import BaseModel

from ee.hogai.tool import search_documentation


def get_core_tool_schemas(team, user) -> list[type[BaseModel]]:
    """
    Return schemas for core tools that should always be available to the agent.
    These are independent of AI Products and contextual UI mounts, but may be gated by settings.
    """
    schemas: list[type[BaseModel]] = []

    if settings.INKEEP_API_KEY:
        schemas.append(search_documentation)

    # TODO:Placeholder for future core tools (e.g., enable_products, search_taxonomy, todo tools)
    return schemas
