import dataclasses
import json
import pytest
from unittest.mock import MagicMock, Mock, patch
from posthog.temporal.ai.session_summary.summarize_session import stream_llm_summary_activity, SessionSummaryInputs
from ee.session_recordings.session_summary.utils import serialize_to_sse_event
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk, Choice, ChoiceDelta
from openai.types.completion_usage import CompletionUsage
from posthog.redis import get_client


class TestStreamLlmSummaryActivity:
    @pytest.mark.asyncio
    async def test_stream_llm_summary_activity_standalone(
        self,
        mock_user: MagicMock,
        mock_valid_llm_yaml_response: str,
        mock_enriched_llm_json_response: dict,
        mock_events_mapping: dict,
        mock_events_columns: list[str],
        mock_url_mapping_reversed: dict[str, str],
        mock_window_mapping_reversed: dict[str, str],
    ):
        def _create_chunk(content: str):
            return ChatCompletionChunk(
                id="test_id",
                choices=[
                    Choice(
                        delta=ChoiceDelta(content=content),
                        index=0,
                        finish_reason=None,
                    )
                ],
                created=1234567890,
                model="gpt-4",
                object="chat.completion.chunk",
                usage=CompletionUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
            )

        async def _mock_stream_llm(*args, **kwargs):
            for chunk_content in yaml_chunks:
                if not chunk_content.strip():
                    continue  # Only yield non-empty chunks
                yield _create_chunk(chunk_content)

        # Split the fixture YAML response into realistic chunks to simulate streaming
        chunk_size = 100
        yaml_chunks = [
            mock_valid_llm_yaml_response[i : i + chunk_size]
            for i in range(0, len(mock_valid_llm_yaml_response), chunk_size)
        ]
        expected_chunk_count = len([chunk for chunk in yaml_chunks if chunk.strip()])
        # Prepare Redis data
        session_id = "test_session_id"
        input_data = SessionSummaryInputs(
            session_id=session_id,
            user_pk=mock_user.pk,
            summary_prompt="Generate a summary for this session",
            system_prompt="You are a helpful assistant that summarizes user sessions",
            simplified_events_mapping=mock_events_mapping,
            simplified_events_columns=mock_events_columns,
            url_mapping_reversed=mock_url_mapping_reversed,
            window_mapping_reversed=mock_window_mapping_reversed,
            session_start_time_str="2025-03-31T18:40:32.302000Z",
            session_duration=5323,
        )
        redis_client = get_client()
        redis_input_key = "test_input_key"
        redis_output_key = "test_output_key"
        redis_client.setex(
            redis_input_key,
            900,  # 15 minutes TTL
            json.dumps(
                {
                    "input_data": dataclasses.asdict(input_data),
                    "output_key": redis_output_key,
                }
            ),
        )
        # Expected SSE events that should be generated
        expected_final_summary = serialize_to_sse_event(
            event_label="session-summary-stream", event_data=json.dumps(mock_enriched_llm_json_response)
        )
        with (
            patch("ee.session_recordings.session_summary.llm.consume.stream_llm", return_value=_mock_stream_llm()),
            patch("temporalio.activity.heartbeat") as mock_heartbeat,
        ):
            # Call the activity directly as a function
            result = await stream_llm_summary_activity(redis_input_key)
            # Verify the result is the final SSE event
            assert result == expected_final_summary
            # Verify heartbeat was called
            assert mock_heartbeat.call_count >= 1
