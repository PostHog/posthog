from uuid import uuid4

from django.conf import settings

import requests

from posthog.schema import AssistantToolCallMessage

from posthog.models import Team, User


def search_codebase_impl(codebase_query: str, tool_call_id: str, team: Team, user: User) -> AssistantToolCallMessage:
    """
    Implementation of codebase search using Relace API.
    Returns an AssistantToolCallMessage with the search results in content.
    """
    if not settings.RELACE_API_KEY:
        return AssistantToolCallMessage(
            content="Codebase search is not configured.",
            ui_payload={},
            id=str(uuid4()),
            tool_call_id=tool_call_id,
            visible=True,
        )

    repo_id = "cb8a7558-131b-403a-9638-6c855c78ea54"
    url = f"https://api.relace.run/v1/repo/{repo_id}/retrieve"
    headers = {
        "Authorization": f"Bearer {settings.RELACE_API_KEY}",
        "Content-Type": "application/json",
    }

    data = {
        "query": codebase_query,
        "include_content": True,
        "rerank": False,  # Minimize latency
        "token_limit": 131072,
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        response.raise_for_status()
        result = response.json()

        if not result.get("results"):
            return AssistantToolCallMessage(
                content="No relevant code found for this query.",
                ui_payload={},
                id=str(uuid4()),
                tool_call_id=tool_call_id,
                visible=True,
            )

        # Format all results with full details in content
        content_lines = [f"Found {len(result['results'])} relevant code locations for '{codebase_query}':\n"]

        for i, item in enumerate(result["results"][:10], 1):  # Limit to top 10 results
            filename = item.get("filename", "unknown")
            score = item.get("score", 0)
            code_content = item.get("content", "")

            content_lines.append(f"\n## {i}. {filename} (relevance: {score:.2f})")
            content_lines.append(f"```\n{code_content}\n```")

        full_content = "\n".join(content_lines)

        return AssistantToolCallMessage(
            content=full_content,
            ui_payload={},
            id=str(uuid4()),
            tool_call_id=tool_call_id,
            visible=True,
        )

    except requests.exceptions.RequestException as e:
        return AssistantToolCallMessage(
            content=f"Failed to search codebase: {str(e)}",
            ui_payload={},
            id=str(uuid4()),
            tool_call_id=tool_call_id,
            visible=True,
        )
