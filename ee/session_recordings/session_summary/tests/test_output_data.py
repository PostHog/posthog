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
from ee.session_recordings.session_summary.prompt_data import SessionSummaryMetadata, SessionSummaryPromptData


class TestLoadRawSessionSummary:
    def test_load_raw_session_summary_success(self, mock_valid_llm_yaml_response: str) -> None:
        allowed_event_ids = ["abcd1234", "defg4567", "ghij7890", "mnop3456", "stuv9012"]
        session_id = "test_session"
        result = load_raw_session_summary_from_llm_content(mock_valid_llm_yaml_response, allowed_event_ids, session_id)
        assert result is not None
        # Ensure the LLM output is valid
        assert result.is_valid()
        # Check segments
        segments = result.data["segments"]
        assert len(segments) == 2
        assert segments[0]["index"] == 0
        assert segments[0]["start_event_id"] == "abcd1234"
        # Check key actions
        key_actions = result.data["key_actions"]
        assert len(key_actions) == 2
        first_segment_actions = key_actions[0]["events"]
        assert len(first_segment_actions) == 2
        assert first_segment_actions[0]["event_id"] == "abcd1234"
        assert first_segment_actions[0]["failure"] is False
        # Check segment outcomes
        segment_outcomes = result.data["segment_outcomes"]
        assert len(segment_outcomes) == 2
        assert segment_outcomes[0]["segment_index"] == 0
        assert segment_outcomes[0]["success"] is True
        # Check session outcome
        session_outcome = result.data["session_outcome"]
        assert session_outcome["success"] is True
        assert "description" in session_outcome

    def test_load_raw_session_summary_no_content(self) -> None:
        session_id = "test_session"
        with pytest.raises(
            SummaryValidationError, match=f"No LLM content found when summarizing session_id {session_id}"
        ):
            load_raw_session_summary_from_llm_content(None, [], session_id)  # type: ignore

    def test_load_raw_session_summary_invalid_yaml(self, mock_valid_llm_yaml_response: str) -> None:
        mock_valid_llm_yaml_response = """```yaml
            invalid: yaml: content:
            - not properly formatted
        ```"""
        session_id = "test_session"
        with pytest.raises(
            SummaryValidationError,
            match=f"Error loading YAML content into JSON when summarizing session_id {session_id}",
        ):
            load_raw_session_summary_from_llm_content(mock_valid_llm_yaml_response, [], session_id)

    def test_load_raw_session_summary_hallucinated_event(self, mock_valid_llm_yaml_response: str) -> None:
        allowed_event_ids = ["abcd1234"]  # Missing other event IDs
        session_id = "test_session"
        with pytest.raises(
            ValueError, match=f"LLM hallucinated event_id defg4567 when summarizing session_id {session_id}"
        ):
            load_raw_session_summary_from_llm_content(mock_valid_llm_yaml_response, allowed_event_ids, session_id)

    def test_load_raw_session_summary_hallucinated_segment_index(self, mock_valid_llm_yaml_response: str) -> None:
        # Modify the YAML to include a key_actions entry with a non-existent segment index
        modified_yaml = mock_valid_llm_yaml_response.replace(
            "segment_index: 1",
            "segment_index: 99",  # This segment index doesn't exist
            1,  # Replace only first occurrence to keep the segment_outcomes valid
        )
        session_id = "test_session"
        with pytest.raises(
            ValueError, match=f"LLM hallucinated segment index 99 when summarizing session_id {session_id}"
        ):
            load_raw_session_summary_from_llm_content(
                modified_yaml, ["abcd1234", "defg4567", "ghij7890", "mnop3456", "stuv9012"], session_id
            )

    def test_load_raw_session_summary_invalid_schema(self, mock_valid_llm_yaml_response: str) -> None:
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
        session_id = "test_session"
        with pytest.raises(
            SummaryValidationError,
            match=f"Error validating LLM output against the schema when summarizing session_id {session_id}",
        ):
            load_raw_session_summary_from_llm_content(modified_yaml, ["abcd1234", "defg4567"], session_id)


@pytest.mark.parametrize(
    "event_time,start_time,expected",
    [
        ("2024-03-01T12:00:02Z", datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC), 2000),  # 2 seconds after
        ("2024-03-01T12:00:00Z", datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC), 0),  # same time
        ("2024-03-01T11:59:59Z", datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC), 0),  # 1 second before (clamped to 0)
        (None, datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC), None),  # no event time
        ("2024-03-01T12:00:02Z", None, None),  # no start time
        ("2024-03-01T13:00:00Z", datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC), 3600000),  # 1 hour after
    ],
)
def test_calculate_time_since_start(event_time: str, start_time: datetime, expected: int) -> None:
    result = calculate_time_since_start(event_time, start_time)
    assert result == expected


class TestEnrichRawSessionSummary:
    @pytest.fixture
    def mock_valid_event_ids(self) -> list[str]:
        return ["abcd1234", "defg4567", "vbgs1287", "gfgz6242", "ghij7890", "mnop3456", "stuv9012"]

    @pytest.fixture
    def mock_raw_session_summary(
        self, mock_valid_llm_yaml_response: str, mock_valid_event_ids: list[str]
    ) -> RawSessionSummarySerializer:
        result = load_raw_session_summary_from_llm_content(
            mock_valid_llm_yaml_response, mock_valid_event_ids, "test_session"
        )
        assert result is not None
        return result

    @pytest.fixture
    def mock_url_mapping_reversed(self) -> dict[str, str]:
        return {
            "url_1": "http://localhost:8010/login",
            "url_2": "http://localhost:8010/signup",
            "url_3": "http://localhost:8010/signup/error",
        }

    @pytest.fixture
    def mock_url_mapping(self, mock_url_mapping_reversed: dict[str, str]) -> dict[str, str]:
        return {v: k for k, v in mock_url_mapping_reversed.items()}

    @pytest.fixture
    def mock_window_mapping_reversed(self) -> dict[str, str]:
        return {
            "window_1": "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
        }

    @pytest.fixture
    def mock_window_mapping(self, mock_window_mapping_reversed: dict[str, str]) -> dict[str, str]:
        return {v: k for k, v in mock_window_mapping_reversed.items()}

    @pytest.fixture
    def mock_events_mapping(
        self,
        mock_raw_events: list[list[Any]],
        mock_url_mapping: dict[str, str],
        mock_window_mapping: dict[str, str],
        mock_valid_event_ids: list[str],
    ) -> dict[str, list[Any]]:
        events_mapping = {}
        for event_index, (event_id, raw_event) in enumerate(zip(mock_valid_event_ids, mock_raw_events)):
            (
                event_type,
                timestamp,
                href,
                texts,
                elements,
                window_id,
                url,
                action_type,
                elements_chain_ids,
                elements_chain,
            ) = raw_event
            events_mapping[event_id] = [
                event_type,
                timestamp.isoformat() + "Z",
                href,
                texts,
                elements,
                mock_window_mapping[window_id],
                mock_url_mapping[url],
                action_type,
                elements_chain_ids,
                elements_chain,
                event_id,
                event_index,
            ]
        return events_mapping

    @pytest.fixture
    def mock_session_metadata(self, mock_raw_metadata: dict[str, Any]) -> SessionSummaryMetadata:
        return SessionSummaryPromptData()._prepare_metadata(mock_raw_metadata)

    def test_enrich_raw_session_summary_success(
        self,
        mock_raw_session_summary: RawSessionSummarySerializer,
        mock_events_mapping: dict[str, list[Any]],
        mock_events_columns: list[str],
        mock_url_mapping_reversed: dict[str, str],
        mock_window_mapping_reversed: dict[str, str],
        mock_session_metadata: SessionSummaryMetadata,
    ) -> None:
        session_id = "test_session"
        result = enrich_raw_session_summary_with_meta(
            mock_raw_session_summary,
            mock_events_mapping,
            mock_events_columns,
            mock_url_mapping_reversed,
            mock_window_mapping_reversed,
            mock_session_metadata,
            session_id,
        )
        # Ensure the enriched content is valid
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
        assert first_event["timestamp"] == "2025-03-31T18:40:39.302000Z"
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
        mock_events_columns: list[str],
        mock_url_mapping_reversed: dict[str, str],
        mock_window_mapping_reversed: dict[str, str],
        mock_session_metadata: SessionSummaryMetadata,
    ) -> None:
        # Remove one event from mapping
        del mock_events_mapping["mnop3456"]
        session_id = "test_session"
        with pytest.raises(
            ValueError, match=f"Mapping data for event_id mnop3456 not found when summarizing session_id {session_id}"
        ):
            enrich_raw_session_summary_with_meta(
                mock_raw_session_summary,
                mock_events_mapping,
                mock_events_columns,
                mock_url_mapping_reversed,
                mock_window_mapping_reversed,
                mock_session_metadata,
                session_id,
            )

    def test_calculate_segment_meta_missing_event(
        self,
        mock_raw_session_summary: RawSessionSummarySerializer,
        mock_events_mapping: dict[str, list[Any]],
        mock_events_columns: list[str],
        mock_url_mapping_reversed: dict[str, str],
        mock_window_mapping_reversed: dict[str, str],
        mock_session_metadata: SessionSummaryMetadata,
    ) -> None:
        # Remove one event from mapping (segment end id)
        del mock_events_mapping["vbgs1287"]
        # Should not raise an error anymore, but use fallback from key actions
        result = enrich_raw_session_summary_with_meta(
            mock_raw_session_summary,
            mock_events_mapping,
            mock_events_columns,
            mock_url_mapping_reversed,
            mock_window_mapping_reversed,
            mock_session_metadata,
            "test_session",
        )
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
        assert segment_with_missing_end_id["meta"]["duration_percentage"] == 0.0007514559458951719
        assert segment_with_missing_end_id["meta"]["events_percentage"] == 0.33333333333333333

    def test_enrich_raw_session_summary_invalid_schema(
        self,
        mock_raw_session_summary: RawSessionSummarySerializer,
        mock_events_mapping: dict[str, list[Any]],
        mock_events_columns: list[str],
        mock_url_mapping_reversed: dict[str, str],
        mock_window_mapping_reversed: dict[str, str],
        mock_session_metadata: SessionSummaryMetadata,
    ) -> None:
        # Change type of the event to the unsupported one to cause schema validation error
        mock_events_mapping["abcd1234"][0] = set()
        session_id = "test_session"
        with pytest.raises(
            SummaryValidationError,
            match=f"Error validating enriched content against the schema when summarizing session_id {session_id}",
        ):
            enrich_raw_session_summary_with_meta(
                mock_raw_session_summary,
                mock_events_mapping,
                mock_events_columns,
                mock_url_mapping_reversed,
                mock_window_mapping_reversed,
                mock_session_metadata,
                session_id,
            )

    def test_enrich_raw_session_summary_missing_url(
        self,
        mock_raw_session_summary: RawSessionSummarySerializer,
        mock_events_mapping: dict[str, list[Any]],
        mock_events_columns: list[str],
        mock_url_mapping_reversed: dict[str, str],
        mock_window_mapping_reversed: dict[str, str],
        mock_session_metadata: SessionSummaryMetadata,
    ) -> None:
        # Remove URL from mapping
        mock_url_mapping_reversed.pop("url_1")
        # Some events are missing URLs (for example, coming from BE, like Python SDK ones), so enrichment should not fail
        enrich_raw_session_summary_with_meta(
            mock_raw_session_summary,
            mock_events_mapping,
            mock_events_columns,
            mock_url_mapping_reversed,
            mock_window_mapping_reversed,
            mock_session_metadata,
            "test_session",
        )

    def test_enrich_raw_session_summary_missing_window_id(
        self,
        mock_raw_session_summary: RawSessionSummarySerializer,
        mock_events_mapping: dict[str, list[Any]],
        mock_events_columns: list[str],
        mock_url_mapping_reversed: dict[str, str],
        mock_window_mapping_reversed: dict[str, str],
        mock_session_metadata: SessionSummaryMetadata,
    ) -> None:
        # Remove window ID from mapping
        mock_window_mapping_reversed.pop("window_1")
        # Some events are missing window IDs (for example, coming from BE, like Python SDK ones), so enrichment should not fail
        enrich_raw_session_summary_with_meta(
            mock_raw_session_summary,
            mock_events_mapping,
            mock_events_columns,
            mock_url_mapping_reversed,
            mock_window_mapping_reversed,
            mock_session_metadata,
            "test_session",
        )

    def test_enrich_raw_session_summary_chronological_sorting(
        self,
        mock_raw_session_summary: RawSessionSummarySerializer,
        mock_events_mapping: dict[str, list[Any]],
        mock_events_columns: list[str],
        mock_url_mapping_reversed: dict[str, str],
        mock_window_mapping_reversed: dict[str, str],
        mock_session_metadata: SessionSummaryMetadata,
    ) -> None:
        # Modify events to have different timestamps
        mock_events_mapping["abcd1234"][1] = "2025-03-31T18:40:39.302000Z"  # Later timestamp
        mock_events_mapping["defg4567"][1] = "2025-03-31T18:40:38.302000Z"  # Earlier timestamp
        session_id = "test_session"
        result = enrich_raw_session_summary_with_meta(
            mock_raw_session_summary,
            mock_events_mapping,
            mock_events_columns,
            mock_url_mapping_reversed,
            mock_window_mapping_reversed,
            mock_session_metadata,
            session_id,
        )
        assert result.is_valid()
        # Check that events are sorted chronologically
        key_actions = result.data["key_actions"]
        assert len(key_actions) > 0
        events = key_actions[0]["events"]
        assert len(events) > 1
        assert events[0]["milliseconds_since_start"] < events[1]["milliseconds_since_start"]
        assert datetime.fromisoformat(events[0]["timestamp"]) < datetime.fromisoformat(events[1]["timestamp"])
