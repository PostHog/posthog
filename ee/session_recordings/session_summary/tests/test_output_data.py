from datetime import UTC, datetime
from typing import Any
import pytest

from ee.session_recordings.session_summary import SummaryValidationError
from ee.session_recordings.session_summary.output_data import (
    RawSessionSummarySerializer,
    calculate_time_since_start,
    enrich_raw_session_summary_with_meta,
    load_raw_session_summary_from_llm_content,
)
from ee.session_recordings.session_summary.prompt_data import SessionSummaryMetadata
from ee.session_recordings.session_summary.utils import get_column_index


class TestLoadRawSessionSummary:
    def test_load_raw_session_summary_success(
        self, mock_valid_llm_yaml_response: str, mock_loaded_llm_json_response: dict[str, Any], mock_session_id: str
    ) -> None:
        allowed_event_ids = ["abcd1234", "defg4567", "ghij7890", "mnop3456", "stuv9012"]
        result = load_raw_session_summary_from_llm_content(
            mock_valid_llm_yaml_response, allowed_event_ids, mock_session_id
        )
        assert result is not None
        # Ensure the LLM output is valid
        assert result.is_valid()
        # Compare the entire structure
        assert result.data == mock_loaded_llm_json_response

    def test_load_raw_session_summary_no_content(self, mock_session_id: str) -> None:
        with pytest.raises(
            SummaryValidationError, match=f"No LLM content found when summarizing session_id {mock_session_id}"
        ):
            load_raw_session_summary_from_llm_content(None, [], mock_session_id)  # type: ignore

    def test_load_raw_session_summary_invalid_yaml(
        self, mock_valid_llm_yaml_response: str, mock_session_id: str
    ) -> None:
        mock_valid_llm_yaml_response = """```yaml
            invalid: yaml: content:
            - not properly formatted
        ```"""
        with pytest.raises(
            SummaryValidationError,
            match=f"Error loading YAML content into JSON when summarizing session_id {mock_session_id}",
        ):
            load_raw_session_summary_from_llm_content(mock_valid_llm_yaml_response, [], mock_session_id)

    def test_load_raw_session_summary_hallucinated_event(
        self, mock_valid_llm_yaml_response: str, mock_session_id: str
    ) -> None:
        allowed_event_ids = ["abcd1234"]  # Missing other event IDs
        with pytest.raises(
            ValueError, match=f"LLM hallucinated event_id defg4567 when summarizing session_id {mock_session_id}"
        ):
            load_raw_session_summary_from_llm_content(mock_valid_llm_yaml_response, allowed_event_ids, mock_session_id)

    def test_load_raw_session_summary_hallucinated_segment_index(
        self, mock_valid_llm_yaml_response: str, mock_session_id: str
    ) -> None:
        # Modify the YAML to include a key_actions entry with a non-existent segment index
        modified_yaml = mock_valid_llm_yaml_response.replace(
            "segment_index: 1",
            "segment_index: 99",  # This segment index doesn't exist
            1,  # Replace only first occurrence to keep the segment_outcomes valid
        )
        with pytest.raises(
            ValueError, match=f"LLM hallucinated segment index 99 when summarizing session_id {mock_session_id}"
        ):
            load_raw_session_summary_from_llm_content(
                modified_yaml, ["abcd1234", "defg4567", "ghij7890", "mnop3456", "stuv9012"], mock_session_id
            )

    def test_load_raw_session_summary_invalid_schema(
        self, mock_valid_llm_yaml_response: str, mock_session_id: str
    ) -> None:
        # Modify the YAML to have invalid schema (wrong type for segment_index, should be integer)
        modified_yaml = """```yaml
segments:
  - index: "not_a_number"
    name: "test"
    start_event_id: abcd1234
    end_event_id: defg4567
key_actions: []
segment_outcomes: []
session_outcome:
  success: true
  description: "test"
        ```"""
        with pytest.raises(
            SummaryValidationError,
            match=f"Error validating LLM output against the schema when summarizing session_id {mock_session_id}",
        ):
            load_raw_session_summary_from_llm_content(modified_yaml, ["abcd1234", "defg4567"], mock_session_id)


@pytest.mark.parametrize(
    "event_time,start_time,expected",
    [
        ("2024-03-01T12:00:02+00:00", datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC), 2000),  # 2 seconds after
        ("2024-03-01T12:00:00+00:00", datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC), 0),  # same time
        ("2024-03-01T11:59:59+00:00", datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC), 0),  # 1 second before (clamped to 0)
        (None, datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC), None),  # no event time
        ("2024-03-01T12:00:02+00:00", None, None),  # no start time
        ("2024-03-01T13:00:00+00:00", datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC), 3600000),  # 1 hour after
    ],
)
def test_calculate_time_since_start(event_time: str, start_time: datetime, expected: int) -> None:
    result = calculate_time_since_start(event_time, start_time)
    assert result == expected


class TestEnrichRawSessionSummary:
    @pytest.fixture
    def mock_raw_session_summary(
        self, mock_valid_llm_yaml_response: str, mock_valid_event_ids: list[str], mock_session_id: str
    ) -> RawSessionSummarySerializer:
        result = load_raw_session_summary_from_llm_content(
            mock_valid_llm_yaml_response, mock_valid_event_ids, mock_session_id
        )
        assert result is not None
        return result

    def test_enrich_raw_session_summary_success(
        self,
        mock_raw_session_summary: RawSessionSummarySerializer,
        mock_events_mapping: dict[str, list[Any]],
        mock_events_columns: list[str],
        mock_event_ids_mapping: dict[str, str],
        mock_url_mapping_reversed: dict[str, str],
        mock_window_mapping_reversed: dict[str, str],
        mock_session_metadata: SessionSummaryMetadata,
        mock_session_id: str,
    ) -> None:
        assert mock_session_metadata.start_time is not None and mock_session_metadata.duration is not None
        result = enrich_raw_session_summary_with_meta(
            raw_session_summary=mock_raw_session_summary,
            simplified_events_mapping=mock_events_mapping,
            event_ids_mapping=mock_event_ids_mapping,
            simplified_events_columns=mock_events_columns,
            url_mapping_reversed=mock_url_mapping_reversed,
            window_mapping_reversed=mock_window_mapping_reversed,
            session_id=mock_session_id,
            session_start_time_str=mock_session_metadata.start_time.isoformat(),
            session_duration=mock_session_metadata.duration,
        )
        assert result.is_valid()
        # Check segments
        segments = result.data["segments"]
        assert len(segments) == 2
        first_segment = segments[0]
        assert first_segment["index"] == 0
        assert first_segment["start_event_id"] == "abcd1234"
        assert first_segment["meta"]["duration"] > 0
        assert first_segment["meta"]["events_count"] > 0
        # Check key actions
        key_actions = result.data["key_actions"]
        assert len(key_actions) == 2
        first_segment_actions = key_actions[0]["events"]
        assert len(first_segment_actions) == 2
        first_event = first_segment_actions[0]
        assert first_event["event"] == "$autocapture"
        assert first_event["timestamp"] == "2025-03-31T18:40:39.302000+00:00"
        assert first_event["window_id"] == "0195ed81-7519-7595-9221-8bb8ddb1fdcc"
        assert first_event["current_url"] == "http://localhost:8010/login"
        assert first_event["event_type"] == "click"
        assert first_event["event_index"] == 0
        # Check events are sorted by timestamp
        assert (
            first_segment_actions[0]["milliseconds_since_start"] < first_segment_actions[1]["milliseconds_since_start"]
        )
        assert datetime.fromisoformat(first_segment_actions[0]["timestamp"]) < datetime.fromisoformat(
            first_segment_actions[1]["timestamp"]
        )

    def test_enrich_raw_session_summary_missing_event(
        self,
        mock_raw_session_summary: RawSessionSummarySerializer,
        mock_events_mapping: dict[str, list[Any]],
        mock_event_ids_mapping: dict[str, str],
        mock_events_columns: list[str],
        mock_url_mapping_reversed: dict[str, str],
        mock_window_mapping_reversed: dict[str, str],
        mock_session_metadata: SessionSummaryMetadata,
        mock_session_id: str,
    ) -> None:
        # Remove one event from mapping
        del mock_events_mapping["mnop3456"]
        assert mock_session_metadata.start_time is not None and mock_session_metadata.duration is not None
        with pytest.raises(
            ValueError,
            match=f"Mapping data for event_id mnop3456 not found when summarizing session_id {mock_session_id}",
        ):
            enrich_raw_session_summary_with_meta(
                raw_session_summary=mock_raw_session_summary,
                simplified_events_mapping=mock_events_mapping,
                event_ids_mapping=mock_event_ids_mapping,
                simplified_events_columns=mock_events_columns,
                url_mapping_reversed=mock_url_mapping_reversed,
                window_mapping_reversed=mock_window_mapping_reversed,
                session_id=mock_session_id,
                session_start_time_str=mock_session_metadata.start_time.isoformat(),
                session_duration=mock_session_metadata.duration,
            )

    def test_calculate_segment_meta_missing_event(
        self,
        mock_raw_session_summary: RawSessionSummarySerializer,
        mock_events_mapping: dict[str, list[Any]],
        mock_event_ids_mapping: dict[str, str],
        mock_events_columns: list[str],
        mock_url_mapping_reversed: dict[str, str],
        mock_window_mapping_reversed: dict[str, str],
        mock_session_metadata: SessionSummaryMetadata,
        mock_session_id: str,
    ) -> None:
        assert mock_session_metadata.start_time is not None and mock_session_metadata.duration is not None
        # Remove one event from mapping (segment end id)
        del mock_events_mapping["vbgs1287"]
        # Should not raise an error anymore, but use fallback from key actions
        result = enrich_raw_session_summary_with_meta(
            raw_session_summary=mock_raw_session_summary,
            simplified_events_mapping=mock_events_mapping,
            event_ids_mapping=mock_event_ids_mapping,
            simplified_events_columns=mock_events_columns,
            url_mapping_reversed=mock_url_mapping_reversed,
            window_mapping_reversed=mock_window_mapping_reversed,
            session_id=mock_session_id,
            session_start_time_str=mock_session_metadata.start_time.isoformat(),
            session_duration=mock_session_metadata.duration,
        )
        assert result.is_valid()
        # Verify the result has segments and the missing event was handled
        assert result.data["segments"] is not None
        assert len(result.data["segments"]) > 0
        # The segment with missing event should have duration and events count processed properly
        segment_with_missing_end_id = next(
            (s for s in result.data["segments"] if s["end_event_id"] == "vbgs1287"),
            None,
        )
        assert segment_with_missing_end_id is not None
        assert segment_with_missing_end_id["meta"] is not None
        assert segment_with_missing_end_id["meta"]["duration"] == 4
        assert segment_with_missing_end_id["meta"]["events_count"] == 2
        assert segment_with_missing_end_id["meta"]["duration_percentage"] == 0.0008
        assert segment_with_missing_end_id["meta"]["events_percentage"] == 0.3333

    def test_enrich_raw_session_summary_invalid_schema(
        self,
        mock_raw_session_summary: RawSessionSummarySerializer,
        mock_events_mapping: dict[str, list[Any]],
        mock_event_ids_mapping: dict[str, str],
        mock_events_columns: list[str],
        mock_url_mapping_reversed: dict[str, str],
        mock_window_mapping_reversed: dict[str, str],
        mock_session_metadata: SessionSummaryMetadata,
        mock_session_id: str,
    ) -> None:
        assert mock_session_metadata.start_time is not None and mock_session_metadata.duration is not None
        # Change type of the event to the unsupported one to cause schema validation error
        event_index = get_column_index(mock_events_columns, "event")
        mock_events_mapping["abcd1234"][event_index] = set()
        with pytest.raises(
            SummaryValidationError,
            match=f"Error validating enriched content against the schema when summarizing session_id {mock_session_id}",
        ):
            enrich_raw_session_summary_with_meta(
                raw_session_summary=mock_raw_session_summary,
                simplified_events_mapping=mock_events_mapping,
                event_ids_mapping=mock_event_ids_mapping,
                simplified_events_columns=mock_events_columns,
                url_mapping_reversed=mock_url_mapping_reversed,
                window_mapping_reversed=mock_window_mapping_reversed,
                session_id=mock_session_id,
                session_start_time_str=mock_session_metadata.start_time.isoformat(),
                session_duration=mock_session_metadata.duration,
            )

    def test_enrich_raw_session_summary_missing_url(
        self,
        mock_raw_session_summary: RawSessionSummarySerializer,
        mock_events_mapping: dict[str, list[Any]],
        mock_event_ids_mapping: dict[str, str],
        mock_events_columns: list[str],
        mock_url_mapping_reversed: dict[str, str],
        mock_window_mapping_reversed: dict[str, str],
        mock_session_metadata: SessionSummaryMetadata,
        mock_session_id: str,
    ) -> None:
        assert mock_session_metadata.start_time is not None and mock_session_metadata.duration is not None
        # Remove URL from mapping
        mock_url_mapping_reversed.pop("url_1")
        # Some events are missing URLs (for example, coming from BE, like Python SDK ones), so enrichment should not fail
        enrich_raw_session_summary_with_meta(
            raw_session_summary=mock_raw_session_summary,
            simplified_events_mapping=mock_events_mapping,
            event_ids_mapping=mock_event_ids_mapping,
            simplified_events_columns=mock_events_columns,
            url_mapping_reversed=mock_url_mapping_reversed,
            window_mapping_reversed=mock_window_mapping_reversed,
            session_id=mock_session_id,
            session_start_time_str=mock_session_metadata.start_time.isoformat(),
            session_duration=mock_session_metadata.duration,
        )

    def test_enrich_raw_session_summary_missing_window_id(
        self,
        mock_raw_session_summary: RawSessionSummarySerializer,
        mock_events_mapping: dict[str, list[Any]],
        mock_event_ids_mapping: dict[str, str],
        mock_events_columns: list[str],
        mock_url_mapping_reversed: dict[str, str],
        mock_window_mapping_reversed: dict[str, str],
        mock_session_metadata: SessionSummaryMetadata,
        mock_session_id: str,
    ) -> None:
        assert mock_session_metadata.start_time is not None and mock_session_metadata.duration is not None
        # Remove window ID from mapping
        mock_window_mapping_reversed.pop("window_1")
        # Some events are missing window IDs (for example, coming from BE, like Python SDK ones), so enrichment should not fail
        enrich_raw_session_summary_with_meta(
            raw_session_summary=mock_raw_session_summary,
            simplified_events_mapping=mock_events_mapping,
            event_ids_mapping=mock_event_ids_mapping,
            simplified_events_columns=mock_events_columns,
            url_mapping_reversed=mock_url_mapping_reversed,
            window_mapping_reversed=mock_window_mapping_reversed,
            session_id=mock_session_id,
            session_start_time_str=mock_session_metadata.start_time.isoformat(),
            session_duration=mock_session_metadata.duration,
        )

    def test_enrich_raw_session_summary_chronological_sorting(
        self,
        mock_raw_session_summary: RawSessionSummarySerializer,
        mock_events_mapping: dict[str, list[Any]],
        mock_event_ids_mapping: dict[str, str],
        mock_events_columns: list[str],
        mock_url_mapping_reversed: dict[str, str],
        mock_window_mapping_reversed: dict[str, str],
        mock_session_metadata: SessionSummaryMetadata,
        mock_session_id: str,
    ) -> None:
        # Modify events to have different timestamps
        timestamp_index = get_column_index(mock_events_columns, "timestamp")
        mock_events_mapping["abcd1234"][timestamp_index] = "2025-03-31T18:40:39.302000+00:00"  # Later timestamp
        mock_events_mapping["defg4567"][timestamp_index] = "2025-03-31T18:40:38.302000+00:00"  # Earlier timestamp
        assert mock_session_metadata.start_time is not None and mock_session_metadata.duration is not None
        result = enrich_raw_session_summary_with_meta(
            raw_session_summary=mock_raw_session_summary,
            simplified_events_mapping=mock_events_mapping,
            event_ids_mapping=mock_event_ids_mapping,
            simplified_events_columns=mock_events_columns,
            url_mapping_reversed=mock_url_mapping_reversed,
            window_mapping_reversed=mock_window_mapping_reversed,
            session_id=mock_session_id,
            session_start_time_str=mock_session_metadata.start_time.isoformat(),
            session_duration=mock_session_metadata.duration,
        )
        assert result.is_valid()
        # Check that events are sorted chronologically
        key_actions = result.data["key_actions"]
        assert len(key_actions) > 0
        events = key_actions[0]["events"]
        assert len(events) > 1
        assert events[0]["milliseconds_since_start"] < events[1]["milliseconds_since_start"]
        assert datetime.fromisoformat(events[0]["timestamp"]) < datetime.fromisoformat(events[1]["timestamp"])

    def test_enrich_raw_session_summary_metadata(
        self,
        mock_raw_session_summary: RawSessionSummarySerializer,
        mock_events_mapping: dict[str, list[Any]],
        mock_event_ids_mapping: dict[str, str],
        mock_events_columns: list[str],
        mock_url_mapping_reversed: dict[str, str],
        mock_window_mapping_reversed: dict[str, str],
        mock_session_metadata: SessionSummaryMetadata,
        mock_session_id: str,
    ) -> None:
        assert mock_session_metadata.start_time is not None and mock_session_metadata.duration is not None
        result = enrich_raw_session_summary_with_meta(
            raw_session_summary=mock_raw_session_summary,
            simplified_events_mapping=mock_events_mapping,
            event_ids_mapping=mock_event_ids_mapping,
            simplified_events_columns=mock_events_columns,
            url_mapping_reversed=mock_url_mapping_reversed,
            window_mapping_reversed=mock_window_mapping_reversed,
            session_id=mock_session_id,
            session_start_time_str=mock_session_metadata.start_time.isoformat(),
            session_duration=mock_session_metadata.duration,
        )
        assert result.is_valid()

        # Expected metadata for segment 0 (successful segment)
        assert result.data["segments"][0]["meta"] == {
            "abandonment_count": 0,
            "confusion_count": 0,
            "duration": 5,
            "duration_percentage": 0.0009,
            "events_count": 3,
            "events_percentage": 0.4286,
            "exception_count": 0,
            "failure_count": 0,
            "key_action_count": 2,
        }

        # Expected metadata for segment 1 (segment with failures)
        assert result.data["segments"][1]["meta"] == {
            "abandonment_count": 1,
            "confusion_count": 1,
            "duration": 17,
            "duration_percentage": 0.0032,
            "events_count": 4,
            "events_percentage": 0.5714,
            "exception_count": 1,
            "failure_count": 2,
            "key_action_count": 3,
        }
