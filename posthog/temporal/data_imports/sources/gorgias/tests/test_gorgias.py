import base64

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.gorgias.gorgias import (
    GorgiasResumeConfig,
    get_base_url,
    get_headers,
    get_rows,
    gorgias_source,
    normalize_domain,
    validate_credentials,
)
from posthog.temporal.data_imports.sources.gorgias.settings import ENDPOINTS, GORGIAS_ENDPOINTS

GORGIAS_MODULE = "posthog.temporal.data_imports.sources.gorgias.gorgias"


class _FakeManager(ResumableSourceManager[GorgiasResumeConfig]):
    """Minimal stand-in for ResumableSourceManager that records saved state in memory."""

    def __init__(self, resume_cursor: str | None = None) -> None:
        self._resume_cursor = resume_cursor
        self.saved: list[GorgiasResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume_cursor is not None

    def load_state(self) -> GorgiasResumeConfig | None:
        return GorgiasResumeConfig(cursor=self._resume_cursor) if self._resume_cursor else None

    def save_state(self, data: GorgiasResumeConfig) -> None:
        self.saved.append(data)


def _response(status_code: int = 200, json_body: dict | None = None, ok: bool = True) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = ok
    response.json.return_value = json_body or {}
    response.text = ""
    return response


class TestNormalizeDomain:
    @parameterized.expand(
        [
            ("bare_subdomain", "acme", "acme"),
            ("full_host", "acme.gorgias.com", "acme"),
            ("https_url", "https://acme.gorgias.com", "acme"),
            ("https_url_with_path", "https://acme.gorgias.com/api/", "acme"),
            ("uppercase_and_spaces", "  ACME  ", "acme"),
            ("trailing_slash", "acme/", "acme"),
        ]
    )
    def test_normalize_domain(self, _name: str, value: str, expected: str) -> None:
        assert normalize_domain(value) == expected

    def test_get_base_url(self) -> None:
        assert get_base_url("acme.gorgias.com") == "https://acme.gorgias.com/api"

    @parameterized.expand(
        [
            # Crafted inputs that would otherwise break out of the .gorgias.com host
            # and redirect the request (and the Basic-auth header) elsewhere.
            ("fragment", "attacker.example.com#"),
            ("query", "169.254.169.254?x="),
            ("userinfo", "user@attacker.example.com"),
            ("port", "attacker.example.com:8080"),
            ("dotted", "evil.com"),
            ("empty", "   "),
            ("leading_hyphen", "-acme"),
        ]
    )
    def test_get_base_url_rejects_unsafe_domains(self, _name: str, domain: str) -> None:
        with pytest.raises(ValueError):
            get_base_url(domain)


class TestHeaders:
    def test_basic_auth_header_is_email_and_api_key(self) -> None:
        headers = get_headers("you@acme.com", "secret-key")
        scheme, _, token = headers["Authorization"].partition(" ")
        assert scheme == "Basic"
        assert base64.b64decode(token).decode() == "you@acme.com:secret-key"
        assert headers["Accept"] == "application/json"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_valid: bool) -> None:
        session = MagicMock()
        session.get.return_value = _response(status_code=status_code)
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            valid, error = validate_credentials("acme", "you@acme.com", "key")
        assert valid is expected_valid
        assert (error is None) is expected_valid

    def test_empty_domain_fails_without_request(self) -> None:
        with patch(f"{GORGIAS_MODULE}.make_tracked_session") as mocked:
            valid, error = validate_credentials("   ", "you@acme.com", "key")
        assert valid is False
        assert error is not None
        mocked.assert_not_called()

    def test_unsafe_domain_fails_without_request(self) -> None:
        with patch(f"{GORGIAS_MODULE}.make_tracked_session") as mocked:
            valid, error = validate_credentials("attacker.example.com#", "you@acme.com", "key")
        assert valid is False
        assert error is not None
        mocked.assert_not_called()

    def test_connection_error_is_handled(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            valid, error = validate_credentials("acme", "you@acme.com", "key")
        assert valid is False
        assert error is not None


class TestGetRows:
    def test_paginates_until_next_cursor_is_null(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(json_body={"data": [{"id": 1}], "meta": {"next_cursor": "c2"}}),
            _response(json_body={"data": [{"id": 2}], "meta": {"next_cursor": None}}),
        ]
        manager = _FakeManager()
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("acme", "e@acme.com", "key", "tickets", MagicMock(), manager))

        assert batches == [[{"id": 1}], [{"id": 2}]]
        assert session.get.call_count == 2

    def test_saves_cursor_after_yielding_each_batch(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(json_body={"data": [{"id": 1}], "meta": {"next_cursor": "c2"}}),
            _response(json_body={"data": [{"id": 2}], "meta": {"next_cursor": None}}),
        ]
        manager = _FakeManager()
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            list(get_rows("acme", "e@acme.com", "key", "tickets", MagicMock(), manager))

        # Only the page that has a following cursor triggers a save.
        assert [c.cursor for c in manager.saved] == ["c2"]

    def test_resumes_from_saved_cursor(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(json_body={"data": [], "meta": {"next_cursor": None}})
        manager = _FakeManager(resume_cursor="resume-token")
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            list(get_rows("acme", "e@acme.com", "key", "tickets", MagicMock(), manager))

        _, kwargs = session.get.call_args
        assert kwargs["params"]["cursor"] == "resume-token"

    def test_passes_explicit_order_by_and_limit(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(json_body={"data": [], "meta": {"next_cursor": None}})
        manager = _FakeManager()
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            list(get_rows("acme", "e@acme.com", "key", "tickets", MagicMock(), manager))

        _, kwargs = session.get.call_args
        assert kwargs["params"]["order_by"] == "created_datetime:asc"
        assert kwargs["params"]["limit"] == 100
        assert "cursor" not in kwargs["params"]

    def test_empty_first_page_terminates(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(json_body={"data": [], "meta": {"next_cursor": None}})
        manager = _FakeManager()
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("acme", "e@acme.com", "key", "tickets", MagicMock(), manager))

        assert batches == []
        assert manager.saved == []


class TestGorgiasSource:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = gorgias_source("acme", "e@acme.com", "key", endpoint, MagicMock(), _FakeManager())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [GORGIAS_ENDPOINTS[endpoint].partition_key]
        assert response.sort_mode == "asc"

    def test_every_endpoint_partitions_on_created_datetime(self) -> None:
        for config in GORGIAS_ENDPOINTS.values():
            assert config.partition_key == "created_datetime"
            assert "updated" not in config.partition_key
