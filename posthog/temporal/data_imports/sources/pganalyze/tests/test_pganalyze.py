import pytest
from unittest import mock

from posthog.temporal.data_imports.sources.pganalyze.pganalyze import (
    PgAnalyzeRetryableError,
    _post_graphql,
    validate_credentials,
)


def _mock_response(status_code: int = 200, json_data: dict | None = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.reason = "OK" if response.ok else "Error"
    response.text = text
    if json_data is None:
        response.json.side_effect = ValueError("no json")
    else:
        response.json.return_value = json_data
    return response


class TestPostGraphql:
    def test_returns_data_on_success(self):
        session = mock.MagicMock()
        session.post.return_value = _mock_response(json_data={"data": {"getServers": []}})

        result = _post_graphql(session, "https://app.pganalyze.com/graphql", "query {}", {})

        assert result == {"getServers": []}

    def test_raises_retryable_on_5xx(self):
        session = mock.MagicMock()
        session.post.return_value = _mock_response(status_code=502, text="bad gateway")

        with pytest.raises(PgAnalyzeRetryableError, match="server error 502"):
            _post_graphql(session, "https://app.pganalyze.com/graphql", "query {}", {})

    def test_raises_retryable_on_429(self):
        session = mock.MagicMock()
        session.post.return_value = _mock_response(status_code=429, text="too many")

        with pytest.raises(PgAnalyzeRetryableError, match="rate limited"):
            _post_graphql(session, "https://app.pganalyze.com/graphql", "query {}", {})

    def test_raises_on_graphql_errors_field(self):
        session = mock.MagicMock()
        session.post.return_value = _mock_response(json_data={"errors": [{"message": "field x not found"}]})

        with pytest.raises(Exception, match="GraphQL error"):
            _post_graphql(session, "https://app.pganalyze.com/graphql", "query {}", {})

    def test_raises_on_missing_data_key(self):
        session = mock.MagicMock()
        session.post.return_value = _mock_response(json_data={"unexpected": "shape"})

        with pytest.raises(Exception, match="Unexpected pganalyze response format"):
            _post_graphql(session, "https://app.pganalyze.com/graphql", "query {}", {})


class TestValidateCredentials:
    def test_returns_true_on_valid_credentials(self):
        with mock.patch("posthog.temporal.data_imports.sources.pganalyze.pganalyze.make_tracked_session") as mock_sess:
            sess = mock.MagicMock()
            sess.post.return_value = _mock_response(json_data={"data": {"getServers": []}})
            mock_sess.return_value = sess

            ok, err = validate_credentials("token", "acme", None)

            assert ok is True
            assert err is None
            sess.post.assert_called_once()
            sess.close.assert_called_once()

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_returns_false_on_auth_error(self, status_code):
        with mock.patch("posthog.temporal.data_imports.sources.pganalyze.pganalyze.make_tracked_session") as mock_sess:
            sess = mock.MagicMock()
            sess.post.return_value = _mock_response(status_code=status_code, text="forbidden")
            mock_sess.return_value = sess

            ok, err = validate_credentials("bad", "acme", None)

            assert ok is False
            assert err is not None
            assert "Invalid" in err

    def test_returns_false_on_graphql_error(self):
        with mock.patch("posthog.temporal.data_imports.sources.pganalyze.pganalyze.make_tracked_session") as mock_sess:
            sess = mock.MagicMock()
            sess.post.return_value = _mock_response(json_data={"errors": [{"message": "Organization not found"}]})
            mock_sess.return_value = sess

            ok, err = validate_credentials("token", "wrong-slug", None)

            assert ok is False
            assert err is not None
            assert "Organization not found" in err
