import json
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from posthog.schema import (
    ArtifactContentType,
    ArtifactSource,
    AssistantToolCallMessage,
    ErrorTrackingFiltersArtifactContent,
)

from posthog.models import Team, User

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tool import MaxTool, ToolMessagesArtifact
from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import ArtifactRefMessage, AssistantState, NodePath

CREATE_ERROR_TRACKING_FILTERS_PROMPT = """
Use this tool to create and persist an Error Tracking filters artifact.

The `filters` object MUST be the same shape as the Error Tracking UI/API query object. Prefer using the canonical `ErrorTrackingQuery` schema.
After creating it, you can execute it by calling `read_data` with kind `error_tracking_filters` and `execute=true`.

IMPORTANT: Use this tool for structured filtering of Error Tracking issues (status/time/environment/assignee/etc).
Do NOT use full-text search for structured filters like "active issues" — that would just search for the keyword "active" in text fields.

Common examples:

1) "Show me active issues"
filters:
{
  "kind": "ErrorTrackingQuery",
  "status": "active"
}

2) "Show me resolved issues"
filters:
{
  "kind": "ErrorTrackingQuery",
  "status": "resolved"
}

3) "Show me suppressed issues"
filters:
{
  "kind": "ErrorTrackingQuery",
  "status": "suppressed"
}

Use this when:
- You need to build or iteratively refine Error Tracking filters.
- You want to reuse the same filters across multiple tool calls without pasting large JSON into chat.
""".strip()

CREATED_TEMPLATE = """
Created Error Tracking filters artifact.

Name: {{{name}}}
Artifact ID: {{{artifact_id}}}
""".strip()


class CreateErrorTrackingFiltersArgs(BaseModel):
    filters: dict[str, Any] = Field(
        ...,
        description="Error Tracking query/filters object (same shape as the UI/API).",
    )
    name: str | None = Field(
        default=None,
        description="Optional human-friendly name for this filter artifact.",
    )
    description: str | None = Field(
        default=None,
        description="Optional description for this filter artifact.",
    )


class CreateErrorTrackingFiltersTool(MaxTool):
    name: Literal["create_error_tracking_filters"] = "create_error_tracking_filters"
    description: str = CREATE_ERROR_TRACKING_FILTERS_PROMPT
    context_prompt_template: str = (
        "Creates an Error Tracking filters artifact (UI/API query object) for later execution"
    )
    args_schema: type[BaseModel] = CreateErrorTrackingFiltersArgs

    @classmethod
    async def create_tool_class(
        cls,
        *,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...] | None = None,
        state: AssistantState | None = None,
        config=None,
        context_manager: AssistantContextManager | None = None,
    ):
        if not context_manager:
            context_manager = AssistantContextManager(team, user, config)

        return cls(
            team=team,
            user=user,
            state=state,
            node_path=node_path,
            config=config,
            args_schema=CreateErrorTrackingFiltersArgs,
            description=CREATE_ERROR_TRACKING_FILTERS_PROMPT,
            context_manager=context_manager,
        )

    async def _arun_impl(self, **kwargs) -> tuple[str, ToolMessagesArtifact | None]:
        args = CreateErrorTrackingFiltersArgs.model_validate(kwargs)

        # Ensure JSON-serializable and not absurdly large.
        try:
            serialized = json.dumps(args.filters, default=str)
        except Exception as e:
            raise MaxToolRetryableError(f"Invalid filters object (must be JSON-serializable): {e}")

        if len(serialized) > 50_000:
            raise MaxToolRetryableError(
                f"Filters object is too large ({len(serialized)} bytes). Please reduce it before saving."
            )

        name = (args.name or "Error tracking filters").strip()
        content = ErrorTrackingFiltersArtifactContent(filters=args.filters)

        artifact = await self._context_manager.artifacts.create_error_tracking_filters(content=content, name=name)

        artifact_ref_message = ArtifactRefMessage(
            content_type=ArtifactContentType.ERROR_TRACKING_FILTERS,
            artifact_id=artifact.short_id,
            source=ArtifactSource.ARTIFACT,
            id=str(uuid4()),
        )

        text_result = format_prompt_string(CREATED_TEMPLATE, name=name, artifact_id=artifact.short_id)
        tool_call_message = AssistantToolCallMessage(
            content=text_result,
            id=str(uuid4()),
            tool_call_id=self.tool_call_id,
        )

        return "", ToolMessagesArtifact(messages=[artifact_ref_message, tool_call_message])
