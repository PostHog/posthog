import re
import json

from langchain_core.messages import AIMessageChunk
from pydantic import ValidationError

from posthog.schema import ArtifactMessage, ArtifactSource, AssistantTool, NotebookArtifactContent

from ee.hogai.tools.create_notebook.parsing import parse_notebook_content_for_streaming
from ee.hogai.tools.create_notebook.tool import CreateNotebookToolArgs

# JSON key used to detect draft notebooks (which should not be streamed)
_DRAFT_CONTENT_JSON_KEY = '"draft_content"'


class NotebookStreamingMixin:
    """
    Mixin that adds notebook streaming support to a stream processor.

    This mixin handles:
    - Detection of create_notebook tool calls during streaming
    - Parsing markdown content into notebook blocks
    - Creating streaming artifact messages for notebook previews

    To use this mixin, the class must have a `_chunks` attribute (dict[str, AIMessageChunk]).
    """

    _chunks: dict[str, AIMessageChunk]

    def _check_for_notebook_streaming(self, chunk: AIMessageChunk) -> ArtifactMessage | None:
        """
        Check for create_notebook tool calls that should be streamed.

        Streaming logic:
        - If `content` field is used → stream the notebook preview
        - If `draft_content` field is used → don't stream (it's a draft)

        The field name appears early in the JSON stream, so we can detect immediately
        whether to stream or not.
        """
        # First try parsed tool_calls (when args JSON is complete or partially parsed)
        found_create_notebook, result = self._check_parsed_tool_calls_for_notebook(chunk)
        if found_create_notebook:
            return result

        # Fallback: check tool_call_chunks for partial streaming
        return self._check_streaming_chunks_for_notebook(chunk)

    def _check_parsed_tool_calls_for_notebook(self, chunk: AIMessageChunk) -> tuple[bool, ArtifactMessage | None]:
        """
        Check parsed tool_calls for create_notebook.

        Returns:
            Tuple of (found_create_notebook, artifact_message).
            - (True, ArtifactMessage) if content should be streamed
            - (True, None) if draft_content is present (don't stream)
            - (False, None) if no create_notebook tool call found
        """
        for tool_call in chunk.tool_calls:
            if tool_call.get("name") == AssistantTool.CREATE_NOTEBOOK:
                args = tool_call.get("args") or {}
                # Validate with schema when possible
                try:
                    validated_args = CreateNotebookToolArgs.model_validate(args)
                    if validated_args.content is not None:
                        return True, self._create_streaming_notebook_artifact(
                            {"content": validated_args.content, "title": validated_args.title}
                        )
                    if validated_args.draft_content is not None:
                        return True, None  # Explicitly don't stream drafts
                except ValidationError:
                    # Partial args, check raw dict for streaming hints
                    if args.get("content") is not None:
                        return True, self._create_streaming_notebook_artifact(args)
                    if args.get("draft_content") is not None:
                        return True, None
                # Neither content nor draft_content yet - continue to check chunks
                return False, None
        return False, None

    def _check_streaming_chunks_for_notebook(self, chunk: AIMessageChunk) -> ArtifactMessage | None:
        """
        Check tool_call_chunks for partial create_notebook streaming.
        Tool_call_chunks contain incremental data before JSON is fully parsed.
        """
        for tool_chunk in chunk.tool_call_chunks:
            if tool_chunk.get("name", "") != AssistantTool.CREATE_NOTEBOOK:
                continue

            args_str = tool_chunk.get("args", "")
            if not args_str:
                continue

            # Check if this is a draft - don't stream drafts
            if _DRAFT_CONTENT_JSON_KEY in args_str:
                return None

            # Try to parse and validate complete JSON first
            try:
                args = json.loads(args_str)
                try:
                    validated_args = CreateNotebookToolArgs.model_validate(args)
                    if validated_args.content is not None:
                        return self._create_streaming_notebook_artifact(
                            {"content": validated_args.content, "title": validated_args.title}
                        )
                except ValidationError:
                    # Schema validation failed, fall back to raw dict
                    if args.get("content") is not None:
                        return self._create_streaming_notebook_artifact(args)
                return None
            except json.JSONDecodeError:
                pass  # JSON incomplete, extract what we can

            # Extract partial content for streaming
            content = self._extract_partial_json_value(args_str, "content")
            if content is not None:
                title = self._extract_partial_json_value(args_str, "title") or ""
                return self._create_streaming_notebook_artifact({"content": content, "title": title})

        return None

    def _extract_partial_json_value(self, json_str: str, key: str) -> str | None:
        """
        Extract a string value from partial/incomplete JSON.
        Handles cases where the JSON is still being streamed.
        """
        # Look for "key": "value" pattern, handling escaped quotes
        pattern = rf'"{key}":\s*"((?:[^"\\]|\\.)*)"'
        match = re.search(pattern, json_str)
        if match:
            # Unescape the value
            value = match.group(1)
            value = value.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
            return value

        # If no closing quote, extract up to the current point (streaming in progress)
        pattern = rf'"{key}":\s*"((?:[^"\\]|\\.)*)'
        match = re.search(pattern, json_str)
        if match:
            value = match.group(1)
            value = value.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
            return value

        return None

    def _create_streaming_notebook_artifact(self, args: dict) -> ArtifactMessage | None:
        """
        Create a streaming ArtifactMessage from create_notebook tool args.
        Uses placeholder VisualizationBlocks for artifact references (actual queries resolved later).

        Note: We create the artifact even with empty content to provide immediate feedback
        that a notebook is being streamed. Content will be populated as chunks arrive.
        """
        content = args.get("content", "")
        title = args.get("title", "")

        # Parse markdown into blocks (with placeholder visualization blocks)
        blocks = self._parse_markdown_to_streaming_blocks(content)

        artifact_content = NotebookArtifactContent(
            blocks=blocks,
            title=title,
        )

        return ArtifactMessage(
            id="temp-notebook",  # Use consistent temp ID so frontend replaces instead of adds
            artifact_id="",  # No artifact ID yet
            source=ArtifactSource.ARTIFACT,
            content=artifact_content,
        )

    def _parse_markdown_to_streaming_blocks(self, content: str) -> list:
        """
        Parse markdown into blocks for streaming.
        Uses shared parsing with strip_incomplete_tags=True for streaming support.
        Creates LoadingBlock placeholders for artifact references since they'll be resolved later.
        """
        return parse_notebook_content_for_streaming(content, strip_incomplete_tags=True)
