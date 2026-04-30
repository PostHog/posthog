import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.resend.resend import (
    RESEND_BASE_URL,
    ResendResumeConfig,
    get_rows,
    resend_source,
    validate_credentials,
)
from posthog.temporal.data_imports.sources.resend.settings import ENDPOINTS, RESEND_ENDPOINTS


def _mock_manager(can_resume: bool = False, state: ResendResumeConfig | None = None) -> MagicMock:
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


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok_200", 200, True),
            ("unauthorized_401", 401, False),
            ("forbidden_403", 403, False),
            ("server_500", 500, False),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.resend.resend.make_tracked_session")
    def test_validate_credentials(self, _name: str, status_code: int, expected: bool, mock_get: MagicMock) -> None:
        mock_get.return_value.get.return_value = _mock_response(status_code=status_code)
        assert validate_credentials("re_test") is expected

        # Auth headers are bound to the session itself; URL is on `.get(...)`.
        session_kwargs = mock_get.call_args.kwargs
        assert session_kwargs["headers"]["Authorization"] == "Bearer re_test"
        called_args, _ = mock_get.return_value.get.call_args
        assert called_args[0] == f"{RESEND_BASE_URL}/domains"

    @patch("posthog.temporal.data_imports.sources.resend.resend.make_tracked_session")
    def test_validate_credentials_network_error_returns_false(self, mock_get: MagicMock) -> None:
        mock_get.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("re_test") is False


class TestFlatEndpoints:
    @parameterized.expand([("audiences",), ("broadcasts",), ("domains",)])
    @patch("posthog.temporal.data_imports.sources.resend.resend.make_tracked_session")
    def test_flat_endpoint_yields_single_batch(self, endpoint: str, mock_get: MagicMock) -> None:
        rows = [{"id": "a1", "created_at": "2026-01-01T00:00:00Z"}]
        mock_get.return_value.get.return_value = _mock_response(json_payload={"data": rows})

        manager = _mock_manager()
        logger = MagicMock()

        tables = list(get_rows("re_test", endpoint, logger, manager))

        assert len(tables) == 1
        assert tables[0].num_rows == 1
        assert tables[0].column("id").to_pylist() == ["a1"]

        called_url = mock_get.return_value.get.call_args[0][0]
        assert called_url == f"{RESEND_BASE_URL}{RESEND_ENDPOINTS[endpoint].path}"

    @patch("posthog.temporal.data_imports.sources.resend.resend.make_tracked_session")
    def test_flat_endpoint_empty_response_yields_nothing(self, mock_get: MagicMock) -> None:
        mock_get.return_value.get.return_value = _mock_response(json_payload={"data": []})
        manager = _mock_manager()
        logger = MagicMock()

        tables = list(get_rows("re_test", "audiences", logger, manager))

        assert tables == []


class TestEmailsPagination:
    @patch("posthog.temporal.data_imports.sources.resend.resend.make_tracked_session")
    def test_paginates_with_has_more_and_saves_state(self, mock_get: MagicMock) -> None:
        page1 = [{"id": f"e{i}", "created_at": "2026-01-01T00:00:00Z"} for i in range(2)]
        page2 = [{"id": f"e{i}", "created_at": "2026-01-01T00:00:00Z"} for i in range(2, 4)]

        mock_get.return_value.get.side_effect = [
            _mock_response(json_payload={"data": page1, "has_more": True}),
            _mock_response(json_payload={"data": page2, "has_more": False}),
        ]

        manager = _mock_manager()
        logger = MagicMock()

        tables = list(get_rows("re_test", "emails", logger, manager))

        assert sum(t.num_rows for t in tables) == 4
        assert mock_get.return_value.get.call_count == 2

        second_call_params = mock_get.return_value.get.call_args_list[1].kwargs["params"]
        assert second_call_params["after"] == "e1"

        manager.save_state.assert_called_once()
        saved: ResendResumeConfig = manager.save_state.call_args[0][0]
        assert saved.next_cursor == "e1"

    @patch("posthog.temporal.data_imports.sources.resend.resend.make_tracked_session")
    def test_resumes_from_saved_cursor(self, mock_get: MagicMock) -> None:
        mock_get.return_value.get.return_value = _mock_response(
            json_payload={"data": [{"id": "e42"}], "has_more": False}
        )

        manager = _mock_manager(can_resume=True, state=ResendResumeConfig(next_cursor="e41"))
        logger = MagicMock()

        list(get_rows("re_test", "emails", logger, manager))

        first_call_params = mock_get.return_value.get.call_args_list[0].kwargs["params"]
        assert first_call_params["after"] == "e41"

    @patch("posthog.temporal.data_imports.sources.resend.resend.make_tracked_session")
    def test_stops_when_has_more_false(self, mock_get: MagicMock) -> None:
        mock_get.return_value.get.return_value = _mock_response(
            json_payload={"data": [{"id": "e1"}], "has_more": False}
        )

        manager = _mock_manager()
        logger = MagicMock()

        list(get_rows("re_test", "emails", logger, manager))

        assert mock_get.return_value.get.call_count == 1
        manager.save_state.assert_not_called()

    @patch("posthog.temporal.data_imports.sources.resend.resend.make_tracked_session")
    def test_raises_when_empty_page_with_has_more_true(self, mock_get: MagicMock) -> None:
        mock_get.return_value.get.return_value = _mock_response(json_payload={"data": [], "has_more": True})

        manager = _mock_manager()
        logger = MagicMock()

        with pytest.raises(ValueError, match="empty page but has_more=True"):
            list(get_rows("re_test", "emails", logger, manager))


class TestContactsFanout:
    @patch("posthog.temporal.data_imports.sources.resend.resend.make_tracked_session")
    def test_fanout_injects_audience_id_and_saves_parent(self, mock_get: MagicMock) -> None:
        audiences = [{"id": "aud_1"}, {"id": "aud_2"}]
        contacts_1 = [{"id": "c1", "email": "a@example.com"}]
        contacts_2 = [{"id": "c2", "email": "b@example.com"}]

        mock_get.return_value.get.side_effect = [
            _mock_response(json_payload={"data": audiences}),
            _mock_response(json_payload={"data": contacts_1}),
            _mock_response(json_payload={"data": contacts_2}),
        ]

        manager = _mock_manager()
        logger = MagicMock()

        tables = list(get_rows("re_test", "contacts", logger, manager))

        # Both audiences' contacts are buffered into one table by the batcher since
        # they're tiny — assert content rather than table count.
        all_rows: list[dict] = []
        for table in tables:
            all_rows.extend(table.to_pylist())

        audience_ids = [row["_audience_id"] for row in all_rows]
        assert sorted(audience_ids) == ["aud_1", "aud_2"]

        contact_urls = [call.args[0] for call in mock_get.return_value.get.call_args_list[1:]]
        assert contact_urls == [
            f"{RESEND_BASE_URL}/audiences/aud_1/contacts",
            f"{RESEND_BASE_URL}/audiences/aud_2/contacts",
        ]

        saved_parent_ids = [call.args[0].last_completed_parent_id for call in manager.save_state.call_args_list]
        assert saved_parent_ids == ["aud_1", "aud_2"]

    @patch("posthog.temporal.data_imports.sources.resend.resend.make_tracked_session")
    def test_fanout_resumes_past_completed_parent(self, mock_get: MagicMock) -> None:
        audiences = [{"id": "aud_1"}, {"id": "aud_2"}, {"id": "aud_3"}]
        contacts_3 = [{"id": "c3"}]

        mock_get.return_value.get.side_effect = [
            _mock_response(json_payload={"data": audiences}),
            _mock_response(json_payload={"data": contacts_3}),
        ]

        manager = _mock_manager(can_resume=True, state=ResendResumeConfig(last_completed_parent_id="aud_2"))
        logger = MagicMock()

        list(get_rows("re_test", "contacts", logger, manager))

        # Only the audiences list fetch + contacts fetch for aud_3 should happen.
        assert mock_get.return_value.get.call_count == 2
        assert mock_get.return_value.get.call_args_list[1].args[0] == f"{RESEND_BASE_URL}/audiences/aud_3/contacts"

    @patch("posthog.temporal.data_imports.sources.resend.resend.make_tracked_session")
    def test_fanout_resumes_from_start_when_completed_parent_deleted(self, mock_get: MagicMock) -> None:
        # If the last completed audience was deleted between syncs we must fall back to a
        # full resync rather than silently skipping every remaining audience.
        audiences = [{"id": "aud_1"}, {"id": "aud_2"}]
        contacts_1 = [{"id": "c1"}]
        contacts_2 = [{"id": "c2"}]

        mock_get.return_value.get.side_effect = [
            _mock_response(json_payload={"data": audiences}),
            _mock_response(json_payload={"data": contacts_1}),
            _mock_response(json_payload={"data": contacts_2}),
        ]

        manager = _mock_manager(can_resume=True, state=ResendResumeConfig(last_completed_parent_id="aud_deleted"))
        logger = MagicMock()

        tables = list(get_rows("re_test", "contacts", logger, manager))

        all_rows: list[dict] = []
        for table in tables:
            all_rows.extend(table.to_pylist())
        assert sorted(row["_audience_id"] for row in all_rows) == ["aud_1", "aud_2"]
        logger.warning.assert_called_once()


class TestSourceResponseShape:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        manager = _mock_manager()
        logger = MagicMock()

        response = resend_source("re_test", endpoint, logger, manager)

        endpoint_config = RESEND_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == [endpoint_config.primary_key]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == [endpoint_config.partition_key]


class TestRetryable:
    @patch("tenacity.nap.time.sleep")
    @patch("posthog.temporal.data_imports.sources.resend.resend.make_tracked_session")
    def test_429_retries_until_success(self, mock_get: MagicMock, _mock_sleep: MagicMock) -> None:
        mock_get.return_value.get.side_effect = [
            _mock_response(status_code=429),
            _mock_response(json_payload={"data": [{"id": "a1"}]}),
        ]

        manager = _mock_manager()
        logger = MagicMock()

        tables = list(get_rows("re_test", "audiences", logger, manager))

        assert len(tables) == 1
        assert mock_get.return_value.get.call_count == 2

    @patch("posthog.temporal.data_imports.sources.resend.resend.make_tracked_session")
    def test_401_does_not_retry_and_raises(self, mock_get: MagicMock) -> None:
        mock_get.return_value.get.return_value = _mock_response(status_code=401)

        manager = _mock_manager()
        logger = MagicMock()

        with pytest.raises(Exception):
            list(get_rows("re_test", "audiences", logger, manager))

        assert mock_get.return_value.get.call_count == 1
