import uuid
from typing import Any, Literal

import structlog
from pydantic import BaseModel, Field

from posthog.schema import ArtifactContentType, ArtifactSource, AssistantTool, AssistantToolCallMessage

from ee.hogai.artifacts.types import StoredNotebookArtifactContent
from ee.hogai.tool import MaxTool, ToolMessagesArtifact
from ee.hogai.tools.create_notebook.parsing import parse_notebook_content_for_storage

logger = structlog.get_logger(__name__)

CREATE_NOTEBOOK_PROMPT = """
Use this tool to create a notebook document with rich content.

# Use this when:
- The user asks for a report, summary, or document
- You want to combine multiple insights with explanatory text
- The user requests a structured analysis or investigation summary
- You want to write a draft notebook for yourself, to review later

# Content vs Draft Content:
You must use EXACTLY ONE of these parameters:
- `content`: Use this when you want to show the notebook to the user immediately. The notebook will be streamed as you write it.
- `draft_content`: Use this when you want to save a draft without showing it to the user. Useful for writing a first version before it's ready, of for taking intermediate finding notes before writing the final version.

# When creating notebook content:
1. Use markdown headings to structure sections (# for main headings, ## for subsections)
2. Reference existing visualization artifacts using <insight>insight_id</insight> tags
3. Include explanatory text around insights to provide context
4. Use bullet points and numbered lists for clarity
5. Include code blocks with triple backticks if showing HogQL or other code

# How to use the <insight>insight_id</insight> tag:
You can use the <insight>insight_id</insight> tag to reference existing visualization insights.
Use the list_data tool with kind=artifacts to retrieve artifact ids, when in doubt.

# Best practices:
The document should be structured as a series of sections, each with a heading and a body.
Try to use each section to answer a single question or provide a single insight.
Don't be verbose, get straight to the point. Data-heavy short documents are preferred over long documents.
Don't repeat yourself. If you've already mentioned an insight or artifact in a previous section, don't mention it again.

# Example content format:
```
# Weekly Analytics Report

## Key Metrics Overview

Here's the main trends insight showing our weekly active users:

<insight>abc123</insight>

As we can see, there's been a 15% increase week-over-week.

## Funnel Analysis

Our signup funnel shows the following conversion rates:

<insight>def456</insight>

### Recommendations

1. Focus on improving step 2 to 3 conversion
2. Consider A/B testing the signup flow
```

# Updating existing notebooks:
- If you want to update an existing notebook, use the `artifact_id` parameter to specify the ID of the existing artifact
- *IMPORTANT*: Updating a notebook will replace the existing content with the new content
"""


class CreateNotebookToolArgs(BaseModel):
    content: str | None = Field(
        default=None,
        description="The notebook content in markdown format. Use this to show the notebook to the user immediately (it will be streamed). Use <insight>artifact_id</insight> tags to reference existing visualization artifacts.",
    )
    draft_content: str | None = Field(
        default=None,
        description="The notebook content in markdown format for a draft. Use this to save a draft without showing it to the user. Use <insight>artifact_id</insight> tags to reference existing visualization artifacts.",
    )
    title: str = Field(description="A descriptive title for the notebook.")
    artifact_id: str | None = Field(
        default=None, description="The ID of an existing notebook artifact that you want to update."
    )


class CreateNotebookTool(MaxTool):
    name: Literal[AssistantTool.CREATE_NOTEBOOK] = AssistantTool.CREATE_NOTEBOOK
    args_schema: type[BaseModel] = CreateNotebookToolArgs
    description: str = CREATE_NOTEBOOK_PROMPT

    def get_required_resource_access(self):
        return [("notebook", "editor")]

    async def _arun_impl(
        self,
        title: str,
        content: str | None = None,
        draft_content: str | None = None,
        artifact_id: str | None = None,
    ) -> tuple[str, Any]:
        # Validate mutual exclusivity of content and draft_content
        if content is not None and draft_content is not None:
            return "Error: Cannot provide both 'content' and 'draft_content'. Use exactly one.", None

        if content is None and draft_content is None:
            return "Error: Either 'content' or 'draft_content' must be provided.", None

        # Determine which content to use and whether this is a draft
        is_draft = draft_content is not None
        notebook_content = draft_content if is_draft else content
        assert notebook_content is not None  # Validated above

        # Parse markdown into StoredBlock[] with artifact references (not full content)
        blocks = parse_notebook_content_for_storage(notebook_content)

        # Create artifact content with reference blocks
        artifact_content = StoredNotebookArtifactContent(
            blocks=blocks,
            title=title,
        )

        artifact = None
        failed_to_update = False
        # Persist artifact
        if artifact_id:
            try:
                artifact = await self._context_manager.artifacts.aupdate(artifact_id, artifact_content)
            except ValueError:
                failed_to_update = True

        if not artifact:
            artifact = await self._context_manager.artifacts.acreate(
                content=artifact_content,
                name=title,
            )

        message = f"The notebook artifact has been created with artifact_id: {artifact.short_id}"
        if failed_to_update:
            message = f"Failed to update the existing notebook artifact. A new artifact has been created with artifact_id: {artifact.short_id}"
        elif artifact_id:
            message = f"The notebook artifact with artifact_id {artifact_id} has been updated"

        if is_draft:
            return message, None

        # Create artifact message for streaming
        artifact_message = self._context_manager.artifacts.create_message(
            artifact_id=artifact.short_id,
            source=ArtifactSource.ARTIFACT,
            content_type=ArtifactContentType.NOTEBOOK,
        )

        return "", ToolMessagesArtifact(
            messages=[
                artifact_message,
                AssistantToolCallMessage(content=message, tool_call_id=self.tool_call_id, id=str(uuid.uuid4())),
            ]
        )
