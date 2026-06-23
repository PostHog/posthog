from posthog.temporal.data_imports.sources.paddle.paddle import PADDLE_BASE_URL, _get_paddle_session


class TestPaddleSession:
    def test_session_retries_rate_limits(self):
        session = _get_paddle_session()
        retry = session.get_adapter(PADDLE_BASE_URL).max_retries

        # A transient 429 must back off and retry rather than failing the whole sync.
        assert retry.total is not None and retry.total > 0
        assert 429 in retry.status_forcelist
        assert retry.respect_retry_after_header is True
        # Persistent failures still surface via response.raise_for_status(), not MaxRetryError.
        assert retry.raise_on_status is False

    def test_auth_failures_are_not_retried(self):
        session = _get_paddle_session()
        retry = session.get_adapter(PADDLE_BASE_URL).max_retries

        # 401/403/400 are credential/config problems handled by get_non_retryable_errors;
        # retrying them would only delay surfacing the error to the user.
        assert 401 not in retry.status_forcelist
        assert 403 not in retry.status_forcelist
        assert 400 not in retry.status_forcelist
