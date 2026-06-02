import base64
from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.mailjet.mailjet import (
    MAILJET_BASE_URL,
    MailjetResumeConfig,
    _get_headers,
    _to_unix_ts,
    get_rows,
    mailjet_source,
    validate_credentials,
)
from posthog.temporal.data_imports.sources.mailjet.settings import ENDPOINTS, MAILJET_ENDPOINTS


def _mock_manager(can_resume: bool = False, state: MailjetResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    manager.save_state = MagicMock()
    return manager


def _mock_response(status_code: int = 200, json_payload: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = json_payload or {}
    response.text = "" if response.ok else "error body"

    def _raise_for_status():
        if not response.ok:
            raise Exception(f"{status_code} Client Error")

    response.raise_for_status.side_effect = _raise_for_status
    return response


def _page(count: int, start: int = 0) -> dict:
    return {"Data": [{"ID": start + i} for i in range(count)], "Count": count, "Total": count}


class TestGetHeaders:
    def test_basic_auth_header_round_trips(self) -> None:
        headers = _get_headers("my_key", "my_secret")
        token = headers["Authorization"].removeprefix("Basic ")
        assert base64.b64decode(token).decode() == "my_key:my_secret"
        assert headers["Accept"] == "application/json"


class TestToUnixTs:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 1, 1, tzinfo=UTC), 1767225600),
            ("naive_datetime", datetime(2026, 1, 1), 1767225600),
            ("int_passthrough", 1767225600, 1767225600),
            ("none", None, None),
            ("string", "not-a-ts", None),
        ]
    )
    def test_to_unix_ts(self, _name: str, value: object, expected: int | None) -> None:
        assert _to_unix_ts(value) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok_200", 200, True),
            ("unauthorized_401", 401, False),
            ("server_500", 500, False),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.mailjet.mailjet.make_tracked_session")
    def test_validate_credentials(self, _name: str, status_code: int, expected: bool, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _mock_response(status_code=status_code)
        assert validate_credentials("key", "secret") is expected

        session_kwargs = mock_session.call_args.kwargs
        token = session_kwargs["headers"]["Authorization"].removeprefix("Basic ")
        assert base64.b64decode(token).decode() == "key:secret"
        called_args, _ = mock_session.return_value.get.call_args
        assert called_args[0] == f"{MAILJET_BASE_URL}/contactmetadata"

    @patch("posthog.temporal.data_imports.sources.mailjet.mailjet.make_tracked_session")
    def test_validate_credentials_network_error_returns_false(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", "secret") is False


class TestOffsetPagination:
    @patch("posthog.temporal.data_imports.sources.mailjet.mailjet.make_tracked_session")
    def test_single_short_page_stops(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _mock_response(json_payload=_page(3))

        tables = list(get_rows("key", "secret", "contact", MagicMock(), _mock_manager()))

        assert sum(t.num_rows for t in tables) == 3
        assert mock_session.return_value.get.call_count == 1

    @patch("posthog.temporal.data_imports.sources.mailjet.mailjet.make_tracked_session")
    def test_multi_page_advances_offset(self, mock_session: MagicMock) -> None:
        limit = MAILJET_ENDPOINTS["contact"].page_size
        mock_session.return_value.get.side_effect = [
            _mock_response(json_payload={"Data": [{"ID": i} for i in range(limit)], "Total": limit + 2}),
            _mock_response(json_payload={"Data": [{"ID": i} for i in range(2)], "Total": limit + 2}),
        ]

        tables = list(get_rows("key", "secret", "contact", MagicMock(), _mock_manager()))

        assert sum(t.num_rows for t in tables) == limit + 2
        assert mock_session.return_value.get.call_count == 2
        first_params = mock_session.return_value.get.call_args_list[0].kwargs["params"]
        second_params = mock_session.return_value.get.call_args_list[1].kwargs["params"]
        assert first_params["Offset"] == 0
        assert second_params["Offset"] == limit

    @patch("posthog.temporal.data_imports.sources.mailjet.mailjet.make_tracked_session")
    def test_exact_multiple_terminates_via_total(self, mock_session: MagicMock) -> None:
        limit = MAILJET_ENDPOINTS["contact"].page_size
        # A full page whose length == limit but Total is reached: must stop without a second request.
        mock_session.return_value.get.return_value = _mock_response(
            json_payload={"Data": [{"ID": i} for i in range(limit)], "Total": limit}
        )

        tables = list(get_rows("key", "secret", "contact", MagicMock(), _mock_manager()))

        assert sum(t.num_rows for t in tables) == limit
        assert mock_session.return_value.get.call_count == 1

    @patch("posthog.temporal.data_imports.sources.mailjet.mailjet.make_tracked_session")
    def test_empty_first_page_yields_nothing(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _mock_response(json_payload={"Data": [], "Total": 0})

        tables = list(get_rows("key", "secret", "contact", MagicMock(), _mock_manager()))

        assert tables == []
        assert mock_session.return_value.get.call_count == 1

    @patch("posthog.temporal.data_imports.sources.mailjet.mailjet.make_tracked_session")
    def test_sort_param_sent(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _mock_response(json_payload=_page(1))

        list(get_rows("key", "secret", "contact", MagicMock(), _mock_manager()))

        params = mock_session.return_value.get.call_args.kwargs["params"]
        assert params["Sort"] == MAILJET_ENDPOINTS["contact"].sort


class TestResume:
    @patch("posthog.temporal.data_imports.sources.mailjet.mailjet.make_tracked_session")
    def test_resumes_from_saved_offset(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _mock_response(json_payload=_page(1))

        manager = _mock_manager(can_resume=True, state=MailjetResumeConfig(offset=1000, endpoint="contact"))
        list(get_rows("key", "secret", "contact", MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[0].kwargs["params"]["Offset"] == 1000

    @patch("posthog.temporal.data_imports.sources.mailjet.mailjet.make_tracked_session")
    def test_resume_ignored_for_other_endpoint(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _mock_response(json_payload=_page(1))

        manager = _mock_manager(can_resume=True, state=MailjetResumeConfig(offset=1000, endpoint="campaign"))
        list(get_rows("key", "secret", "contact", MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[0].kwargs["params"]["Offset"] == 0

    @patch("posthog.temporal.data_imports.sources.mailjet.mailjet.make_tracked_session")
    def test_save_state_uses_post_increment_offset(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _mock_response(json_payload=_page(3))

        manager = _mock_manager()
        list(get_rows("key", "secret", "contact", MagicMock(), manager))

        saved: MailjetResumeConfig = manager.save_state.call_args[0][0]
        assert saved.offset == 3
        assert saved.endpoint == "contact"


class TestIncremental:
    @patch("posthog.temporal.data_imports.sources.mailjet.mailjet.make_tracked_session")
    def test_from_ts_applied_for_statistics_endpoint(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _mock_response(json_payload=_page(1))

        list(
            get_rows(
                "key",
                "secret",
                "openinformation",
                MagicMock(),
                _mock_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        params = mock_session.return_value.get.call_args.kwargs["params"]
        assert params["FromTS"] == 1767225600

    @patch("posthog.temporal.data_imports.sources.mailjet.mailjet.make_tracked_session")
    def test_from_ts_not_applied_for_full_refresh_endpoint(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _mock_response(json_payload=_page(1))

        list(
            get_rows(
                "key",
                "secret",
                "contact",
                MagicMock(),
                _mock_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert "FromTS" not in mock_session.return_value.get.call_args.kwargs["params"]


class TestSourceResponseShape:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = mailjet_source("key", "secret", endpoint, MagicMock(), _mock_manager())
        config = MAILJET_ENDPOINTS[endpoint]

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestRetryable:
    @patch("tenacity.nap.time.sleep")
    @patch("posthog.temporal.data_imports.sources.mailjet.mailjet.make_tracked_session")
    def test_429_retries_until_success(self, mock_session: MagicMock, _mock_sleep: MagicMock) -> None:
        mock_session.return_value.get.side_effect = [
            _mock_response(status_code=429),
            _mock_response(json_payload=_page(1)),
        ]

        tables = list(get_rows("key", "secret", "contact", MagicMock(), _mock_manager()))

        assert sum(t.num_rows for t in tables) == 1
        assert mock_session.return_value.get.call_count == 2

    @patch("posthog.temporal.data_imports.sources.mailjet.mailjet.make_tracked_session")
    def test_401_does_not_retry_and_raises(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _mock_response(status_code=401)

        with pytest.raises(Exception):
            list(get_rows("key", "secret", "contact", MagicMock(), _mock_manager()))

        assert mock_session.return_value.get.call_count == 1
