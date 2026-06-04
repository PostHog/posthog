from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

import orjson
import requests
import structlog
from parameterized import parameterized

from posthog.temporal.data_imports.sources.mixpanel import mixpanel as mp
from posthog.temporal.data_imports.sources.mixpanel.mixpanel import (
    MixpanelResumeConfig,
    MixpanelRetryableError,
    _check_response,
    _export_base,
    _flatten_event,
    _flatten_profile,
    _query_base,
    _to_date,
    mixpanel_source,
    validate_credentials,
)
from posthog.temporal.data_imports.sources.mixpanel.settings import MIXPANEL_ENDPOINTS

LOGGER = structlog.get_logger()


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        json_data: Any = None,
        lines: Optional[list[bytes]] = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._json = json_data
        self._lines = lines or []
        self.text = text

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def json(self) -> Any:
        return self._json

    def iter_lines(self):
        return iter(self._lines)

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)  # type: ignore[arg-type]

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        return None


class FakeManager:
    """Stand-in for ResumableSourceManager that records saved state in memory."""

    def __init__(self, resume_state: Optional[MixpanelResumeConfig] = None) -> None:
        self._state = resume_state
        self.saved: list[MixpanelResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> Optional[MixpanelResumeConfig]:
        return self._state

    def save_state(self, data: MixpanelResumeConfig) -> None:
        self.saved.append(data)


class TestFlatten:
    def test_flatten_event_lifts_properties(self) -> None:
        row = _flatten_event(
            {"event": "Signup", "properties": {"time": 1700000000, "distinct_id": "u1", "$insert_id": "abc"}}
        )
        assert row == {"event": "Signup", "time": 1700000000, "distinct_id": "u1", "$insert_id": "abc"}

    def test_flatten_event_without_properties(self) -> None:
        assert _flatten_event({"event": "Signup"}) == {"event": "Signup"}

    def test_flatten_event_ignores_non_dict_properties(self) -> None:
        assert _flatten_event({"event": "X", "properties": None}) == {"event": "X"}

    def test_flatten_profile_lifts_properties(self) -> None:
        row = _flatten_profile({"$distinct_id": "u1", "$properties": {"$email": "a@b.com", "plan": "pro"}})
        assert row == {"$distinct_id": "u1", "$email": "a@b.com", "plan": "pro"}

    def test_flatten_profile_without_properties(self) -> None:
        assert _flatten_profile({"$distinct_id": "u1"}) == {"$distinct_id": "u1"}


class TestToDate:
    @parameterized.expand(
        [
            ("epoch_int", 1700000000, date(2023, 11, 14)),
            ("epoch_float", 1700000000.0, date(2023, 11, 14)),
            ("aware_datetime", datetime(2024, 5, 1, 23, 0, tzinfo=UTC), date(2024, 5, 1)),
            ("naive_datetime", datetime(2024, 5, 1, 12, 0), date(2024, 5, 1)),
            ("date_value", date(2024, 5, 1), date(2024, 5, 1)),
            ("iso_string", "2024-05-01T10:00:00Z", date(2024, 5, 1)),
            ("date_string", "2024-05-01", date(2024, 5, 1)),
            ("none", None, None),
            ("bad_string", "not-a-date", None),
            ("bool", True, None),
        ]
    )
    def test_to_date(self, _name: str, value: Any, expected: Optional[date]) -> None:
        assert _to_date(value) == expected


class TestRegionHosts:
    @parameterized.expand(
        [
            ("us", "https://mixpanel.com", "https://data.mixpanel.com"),
            ("eu", "https://eu.mixpanel.com", "https://data-eu.mixpanel.com"),
            ("in", "https://in.mixpanel.com", "https://data-in.mixpanel.com"),
            ("unknown", "https://mixpanel.com", "https://data.mixpanel.com"),
        ]
    )
    def test_region_resolution(self, region: str, expected_query: str, expected_export: str) -> None:
        assert _query_base(region) == expected_query
        assert _export_base(region) == expected_export


class TestCheckResponse:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        with pytest.raises(MixpanelRetryableError):
            _check_response(FakeResponse(status_code=status), "http://x", LOGGER)  # type: ignore[arg-type]

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name: str, status: int) -> None:
        with pytest.raises(requests.HTTPError):
            _check_response(FakeResponse(status_code=status), "http://x", LOGGER)  # type: ignore[arg-type]

    def test_ok_returns_response(self) -> None:
        response = FakeResponse(status_code=200)
        assert _check_response(response, "http://x", LOGGER) is response  # type: ignore[arg-type, comparison-overlap]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("forbidden_at_create", 403, None, True),
            ("forbidden_with_schema", 403, "export", False),
            ("unexpected", 500, None, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, schema_name: Optional[str], expected_ok: bool) -> None:
        session = MagicMock()
        session.post.return_value = FakeResponse(status_code=status)
        with patch.object(mp, "make_tracked_session", return_value=session):
            ok, error = validate_credentials("us", "user", "secret", "123", schema_name=schema_name)
        assert ok is expected_ok
        if expected_ok:
            assert error is None
        else:
            assert error is not None

    def test_network_error_returns_failure(self) -> None:
        session = MagicMock()
        session.post.side_effect = requests.ConnectionError("boom")
        with patch.object(mp, "make_tracked_session", return_value=session):
            ok, error = validate_credentials("eu", "user", "secret", "123")
        assert ok is False
        assert error is not None


class TestExportIterator:
    def _run(self, manager: FakeManager, start: date, end: date, responses: list[FakeResponse]) -> list[dict]:
        with patch.object(mp, "_request", side_effect=responses) as mock_request:
            batches = list(
                mp._iter_export("us", "u", "s", "123", LOGGER, manager, start_date=start, end_date=end)  # type: ignore[arg-type]
            )
        self._mock_request = mock_request
        return [row for batch in batches for row in batch]

    def test_streams_jsonl_per_day_and_saves_state(self) -> None:
        manager = FakeManager()
        day1 = [orjson.dumps({"event": "A", "properties": {"time": 1, "distinct_id": "u", "$insert_id": "i1"}})]
        day2 = [orjson.dumps({"event": "B", "properties": {"time": 2, "distinct_id": "u", "$insert_id": "i2"}})]
        rows = self._run(
            manager,
            date(2024, 1, 1),
            date(2024, 1, 2),
            [FakeResponse(lines=day1), FakeResponse(lines=day2)],
        )

        assert [r["event"] for r in rows] == ["A", "B"]
        # One request per day window
        assert self._mock_request.call_count == 2
        first_call = self._mock_request.call_args_list[0]
        assert first_call.kwargs["params"]["from_date"] == "2024-01-01"
        assert first_call.kwargs["params"]["to_date"] == "2024-01-01"
        # State advances to the day AFTER each completed window
        assert [s.from_date for s in manager.saved] == ["2024-01-02", "2024-01-03"]

    def test_resumes_from_saved_state(self) -> None:
        manager = FakeManager(MixpanelResumeConfig(from_date="2024-01-02"))
        rows = self._run(
            manager,
            date(2024, 1, 1),
            date(2024, 1, 2),
            [FakeResponse(lines=[orjson.dumps({"event": "B", "properties": {"time": 2}})])],
        )
        # Only the resumed day is fetched, the earlier day is skipped
        assert self._mock_request.call_count == 1
        assert self._mock_request.call_args_list[0].kwargs["params"]["from_date"] == "2024-01-02"
        assert [r["event"] for r in rows] == ["B"]

    def test_empty_day_still_advances(self) -> None:
        manager = FakeManager()
        rows = self._run(manager, date(2024, 1, 1), date(2024, 1, 1), [FakeResponse(lines=[])])
        assert rows == []
        assert [s.from_date for s in manager.saved] == ["2024-01-02"]


class TestEngageIterator:
    def test_paginates_with_session_id_and_saves_state(self) -> None:
        manager = FakeManager()
        page0 = FakeResponse(
            json_data={
                "page": 0,
                "page_size": 2,
                "session_id": "sess-1",
                "results": [
                    {"$distinct_id": "a", "$properties": {"x": 1}},
                    {"$distinct_id": "b", "$properties": {"x": 2}},
                ],
            }
        )
        page1 = FakeResponse(
            json_data={
                "page": 1,
                "page_size": 2,
                "session_id": "sess-1",
                "results": [{"$distinct_id": "c", "$properties": {"x": 3}}],
            }
        )
        with patch.object(mp, "_request", side_effect=[page0, page1]) as mock_request:
            batches = list(mp._iter_engage("us", "u", "s", "123", LOGGER, manager))  # type: ignore[arg-type]

        rows = [row for batch in batches for row in batch]
        assert [r["$distinct_id"] for r in rows] == ["a", "b", "c"]
        # Second request carries the session_id and the next page
        second_params = mock_request.call_args_list[1].kwargs["params"]
        assert second_params["session_id"] == "sess-1"
        assert second_params["page"] == 1
        assert manager.saved[-1].page == 2
        assert manager.saved[-1].session_id == "sess-1"

    def test_resumes_from_saved_page(self) -> None:
        manager = FakeManager(MixpanelResumeConfig(session_id="sess-9", page=3))
        page = FakeResponse(json_data={"page": 3, "page_size": 10, "session_id": "sess-9", "results": []})
        with patch.object(mp, "_request", side_effect=[page]) as mock_request:
            list(mp._iter_engage("us", "u", "s", "123", LOGGER, manager))  # type: ignore[arg-type]
        params = mock_request.call_args_list[0].kwargs["params"]
        assert params["page"] == 3
        assert params["session_id"] == "sess-9"


class TestSingleRequestEndpoints:
    def test_cohorts_handles_bare_list(self) -> None:
        with patch.object(mp, "_request", return_value=FakeResponse(json_data=[{"id": 1}, {"id": 2}])):
            batches = list(mp._fetch_cohorts("us", "u", "s", "123", LOGGER))
        assert batches == [[{"id": 1}, {"id": 2}]]

    def test_annotations_handles_results_wrapper(self) -> None:
        with patch.object(mp, "_request", return_value=FakeResponse(json_data={"results": [{"id": 5}]})):
            batches = list(mp._fetch_annotations("us", "u", "s", "123", LOGGER))
        assert batches == [[{"id": 5}]]

    def test_empty_results_yields_nothing(self) -> None:
        with patch.object(mp, "_request", return_value=FakeResponse(json_data={"results": []})):
            assert list(mp._fetch_annotations("us", "u", "s", "123", LOGGER)) == []


class TestGetRowsExportWindow:
    def _captured_window(self, **kwargs) -> tuple[date, date]:
        with patch.object(mp, "_iter_export", return_value=iter([])) as mock_iter:
            list(mp.get_rows("us", "u", "s", "123", "export", LOGGER, FakeManager(), **kwargs))  # type: ignore[arg-type]
        call = mock_iter.call_args
        return call.kwargs["start_date"], call.kwargs["end_date"]

    def test_future_cursor_clamps_start_to_today(self) -> None:
        future = int(datetime(2999, 1, 1, tzinfo=UTC).timestamp())
        start_date, end_date = self._captured_window(
            should_use_incremental_field=True, db_incremental_field_last_value=future
        )
        assert start_date == end_date == datetime.now(UTC).date()

    def test_past_cursor_used_as_start(self) -> None:
        past = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())
        start_date, end_date = self._captured_window(
            should_use_incremental_field=True, db_incremental_field_last_value=past
        )
        assert start_date == date(2020, 1, 1)
        assert end_date == datetime.now(UTC).date()


class TestMixpanelSource:
    @parameterized.expand(
        [
            ("export", ["$insert_id", "event", "distinct_id", "time"], "datetime", "time"),
            ("engage", ["$distinct_id"], None, None),
            ("cohorts", ["id"], "datetime", "created"),
            ("annotations", ["id"], None, None),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], partition_mode: Optional[str], partition_key: Optional[str]
    ) -> None:
        response = mixpanel_source("us", "u", "s", "123", endpoint, LOGGER, FakeManager())  # type: ignore[arg-type]
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_mode == partition_mode
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.sort_mode == "asc"

    def test_endpoints_cover_settings(self) -> None:
        # Guard against a settings/transport mismatch in the routing switch
        for endpoint in MIXPANEL_ENDPOINTS:
            response = mixpanel_source("us", "u", "s", "123", endpoint, LOGGER, FakeManager())  # type: ignore[arg-type]
            assert response.name == endpoint
