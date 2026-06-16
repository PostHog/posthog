from types import SimpleNamespace

import pytest
from unittest import mock

from google.ads.googleads.errors import GoogleAdsException
from google.ads.googleads.v23.enums import types as ga_enums
from google.ads.googleads.v23.errors.types.errors import ErrorCode, GoogleAdsError, GoogleAdsFailure
from google.ads.googleads.v23.errors.types.request_error import RequestErrorEnum

from posthog.models.integration import Integration
from posthog.temporal.data_imports.sources.generated_configs import GoogleAdsSourceConfig
from posthog.temporal.data_imports.sources.google_ads.configs import GoogleAdsResumeConfig, clean_customer_id
from posthog.temporal.data_imports.sources.google_ads.google_ads import (
    GoogleAdsColumn,
    GoogleAdsTable,
    _is_invalid_page_token_error,
    _search_as_arrow_tables,
)
from posthog.temporal.data_imports.sources.google_ads.source import GoogleAdsSource

_CUSTOMER_ID_ERROR = "valid Google Ads customer ID"
_MANAGER_ID_ERROR = "valid Google Ads manager customer ID"


class TestCleanCustomerId:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("123-456-7890", "1234567890"),
            ("1234567890", "1234567890"),
            ("  123-456-7890  ", "1234567890"),
            ("123 456 7890", "1234567890"),
            ("", ""),
            (None, None),
        ],
    )
    def test_strips_to_bare_digits(self, raw, expected):
        assert clean_customer_id(raw) == expected


class TestGoogleAdsValidateConfig:
    def setup_method(self):
        self.source = GoogleAdsSource()

    def _customer_id_errors(self, job_inputs: dict) -> list[str]:
        _, errors = self.source.validate_config(job_inputs)
        return [e for e in errors if _CUSTOMER_ID_ERROR in e]

    def _manager_id_errors(self, job_inputs: dict) -> list[str]:
        _, errors = self.source.validate_config(job_inputs)
        return [e for e in errors if _MANAGER_ID_ERROR in e]

    @pytest.mark.parametrize(
        "customer_id",
        ["123-456-7890", "1234567890", "123 456 7890", "  123-456-7890  "],
    )
    def test_accepts_any_common_customer_id_format(self, customer_id):
        assert self._customer_id_errors({"customer_id": customer_id}) == []

    @pytest.mark.parametrize(
        "customer_id",
        ["12345", "123-456-789", "abcd", "123-456-78901"],
    )
    def test_rejects_invalid_customer_id(self, customer_id):
        assert len(self._customer_id_errors({"customer_id": customer_id})) == 1

    @pytest.mark.parametrize(
        "mcc_client_id",
        ["123-456-7890", "1234567890", "123 456 7890", "  123-456-7890  "],
    )
    def test_accepts_any_common_manager_customer_id_format(self, mcc_client_id):
        job_inputs = {
            "customer_id": "1234567890",
            "is_mcc_account": {"enabled": True, "mcc_client_id": mcc_client_id},
        }
        assert self._manager_id_errors(job_inputs) == []

    def test_rejects_invalid_manager_customer_id(self):
        job_inputs = {
            "customer_id": "1234567890",
            "is_mcc_account": {"enabled": True, "mcc_client_id": "123"},
        }
        assert len(self._manager_id_errors(job_inputs)) == 1


class TestGoogleAdsNonRetryableErrors:
    def setup_method(self):
        self.source = GoogleAdsSource()
        self.non_retryable = self.source.get_non_retryable_errors()

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Real RefreshError string observed in production when the refresh
            # token has been revoked / expired — reported by `str(e)` on
            # google.auth.exceptions.RefreshError.
            "('invalid_grant: Bad Request', {'error': 'invalid_grant', 'error_description': 'Bad Request'})",
            "('invalid_grant: Token has been expired or revoked.', {'error': 'invalid_grant', 'error_description': 'Token has been expired or revoked.'})",
            "('invalid_grant: Invalid grant: account not found', {'error': 'invalid_grant', 'error_description': 'Invalid grant: account not found'})",
        ],
    )
    def test_invalid_grant_is_non_retryable(self, error_msg):
        assert any(pattern in error_msg for pattern in self.non_retryable), (
            f"RefreshError message {error_msg!r} did not match any non-retryable pattern"
        )

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Real RefreshError strings observed in production when a Google Workspace
            # admin has restricted third-party API access for the app. Reported by
            # `str(e)` on google.auth.exceptions.RefreshError.
            (
                "('access_not_configured: Access to your account data (which may include HIPAA and PHI data) is "
                "restricted by policies within your organization. Please contact the administrator of your "
                "organization for more information regarding API access from third-party applications.', "
                "{'error': 'access_not_configured', 'error_description': 'Access to your account data ...'})"
            ),
            (
                "('access_not_configured: You can't access this app until an admin at your institution reviews "
                "and configures access for it. If you need access to this app,', {'error': 'access_not_configured', "
                "'error_description': 'You can't access this app ...'})"
            ),
        ],
    )
    def test_access_not_configured_is_non_retryable(self, error_msg):
        assert any(pattern in error_msg for pattern in self.non_retryable), (
            f"RefreshError message {error_msg!r} did not match any non-retryable pattern"
        )

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Observed in production: requesting metrics against a manager (MCC) account.
            (
                "errors {\n  error_code {\n    query_error: REQUESTED_METRICS_FOR_MANAGER\n  }\n  "
                'message: "Metrics cannot be requested for a manager account. To retrieve metrics, '
                'issue separate requests against each client account under the manager account."\n}\n'
            ),
            # Other Google Ads specific failures that should stop retrying.
            "PERMISSION_DENIED: The caller does not have permission",
            "UNAUTHENTICATED: Request had invalid authentication credentials",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT: Request had insufficient authentication scopes",
            "Customer: Account has been deleted",
            "INVALID_CUSTOMER_ID: Customer ID is not valid",
        ],
    )
    def test_permanent_auth_errors_are_non_retryable(self, error_msg):
        is_non_retryable = any(pattern in error_msg for pattern in self.non_retryable.keys())
        assert is_non_retryable, f"Expected error to be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # `str(Integration.DoesNotExist)` as raised by `google_ads_client` during a sync when
            # the OAuth integration row has been deleted/disconnected.
            "Integration matching query does not exist.",
        ],
    )
    def test_missing_integration_is_non_retryable(self, error_msg):
        is_non_retryable = any(pattern in error_msg for pattern in self.non_retryable.keys())
        assert is_non_retryable, f"Expected error to be non-retryable: {error_msg}"

    def test_missing_integration_has_friendly_message(self):
        friendly = self.non_retryable["Integration matching query does not exist"]
        assert friendly is not None
        assert "reconnect" in friendly.lower()

    def test_other_model_does_not_exist_is_not_swallowed(self):
        # The pattern is model-specific so an unrelated model's DoesNotExist — which may be a real
        # bug — is not silently treated as non-retryable.
        error_msg = "ExternalDataSchema matching query does not exist."
        assert not any(pattern in error_msg for pattern in self.non_retryable.keys())

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Transient network/infrastructure errors should still be retried.
            "DeadlineExceeded: 504 Deadline Exceeded",
            "UNAVAILABLE: The service is currently unavailable",
            "ConnectionError: Connection reset by peer",
            "INTERNAL: Internal server error",
            # A RefreshError wrapping a transient 502 from Google's token endpoint shares the
            # same error-tracking group as access_not_configured but must remain retryable.
            "('<!DOCTYPE html><title>Error 502 (Server Error)!!1</title>', None)",
        ],
    )
    def test_transient_errors_are_retryable(self, error_msg):
        is_non_retryable = any(pattern in error_msg for pattern in self.non_retryable.keys())
        assert not is_non_retryable, f"Expected error to be retryable: {error_msg}"

    @pytest.mark.parametrize(
        "pattern",
        [
            "PERMISSION_DENIED",
            "UNAUTHENTICATED",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
            "Account has been deleted",
            "INVALID_CUSTOMER_ID",
            "REQUESTED_METRICS_FOR_MANAGER",
            "invalid_grant",
            "access_not_configured",
        ],
    )
    def test_documented_patterns_present(self, pattern):
        assert pattern in self.non_retryable

    def test_requested_metrics_for_manager_has_user_facing_message(self):
        message = self.non_retryable["REQUESTED_METRICS_FOR_MANAGER"]
        assert message is not None
        assert "manager" in message.lower()

    def test_invalid_grant_has_friendly_message(self):
        friendly = self.non_retryable["invalid_grant"]
        assert friendly is not None
        assert "reconnect" in friendly.lower()

    def test_access_not_configured_has_friendly_message(self):
        friendly = self.non_retryable["access_not_configured"]
        assert friendly is not None
        assert "admin" in friendly.lower()


class TestValidateCredentials:
    def test_missing_integration_does_not_exist_returns_reconnect_message(self):
        # `google_ads_client` calls `Integration.objects.get(...)`, which raises the typed
        # `Integration.DoesNotExist` when the OAuth connection row is gone. Surface an
        # actionable reconnect message instead of the raw ORM error.
        config = GoogleAdsSourceConfig(customer_id="1234567890", google_ads_integration_id=1)
        with mock.patch(
            "posthog.temporal.data_imports.sources.google_ads.google_ads.google_ads_client",
            side_effect=Integration.DoesNotExist(),
        ):
            ok, message = GoogleAdsSource().validate_credentials(config, team_id=1)

        assert ok is False
        assert "no longer exists" in (message or "")
        assert "Integration matching query" not in (message or "")

    def test_missing_integration_string_match_returns_friendly_message(self):
        # The same condition can also surface as a generic exception whose message contains
        # the ORM "matching query does not exist" text; still surface a reconnect message.
        config = GoogleAdsSourceConfig(customer_id="123-456-7890", google_ads_integration_id=1)
        with mock.patch(
            "posthog.temporal.data_imports.sources.google_ads.google_ads.google_ads_client",
            side_effect=Exception("Integration matching query does not exist"),
        ):
            ok, message = GoogleAdsSource().validate_credentials(config, team_id=1)

        assert ok is False
        assert "reconnect your Google Ads account" in (message or "")


def _google_ads_exception(request_error: RequestErrorEnum.RequestError) -> GoogleAdsException:
    failure = GoogleAdsFailure(
        errors=[
            GoogleAdsError(
                error_code=ErrorCode(request_error=request_error),
                message="Page token is invalid."
                if request_error == RequestErrorEnum.RequestError.INVALID_PAGE_TOKEN
                else "boom",
            )
        ]
    )
    return GoogleAdsException(error=None, call=None, failure=failure, request_id="req-1")


def _string_column(qualified_name: str) -> GoogleAdsColumn:
    return GoogleAdsColumn(
        qualified_name=qualified_name,
        data_type=ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.STRING,
        is_repeatable=False,
        type_url="",
    )


def _single_row_table() -> GoogleAdsTable:
    return GoogleAdsTable(
        name="campaign",
        alias="campaign",
        columns=[_string_column("campaign.name")],
        parents=None,
        requires_filter=False,
        primary_key=[],
        should_sync_default=True,
        description=None,
    )


def _single_page() -> SimpleNamespace:
    return SimpleNamespace(
        field_mask=SimpleNamespace(paths=["campaign.name"]),
        results=[SimpleNamespace(campaign=SimpleNamespace(name="Acme"))],
        next_page_token="",
    )


class _FakeService:
    """Raises INVALID_PAGE_TOKEN for any non-empty token, succeeds on the first page."""

    def __init__(self, page: SimpleNamespace, error_on_token: GoogleAdsException | None = None):
        self.page = page
        self.error_on_token = error_on_token or _google_ads_exception(RequestErrorEnum.RequestError.INVALID_PAGE_TOKEN)
        self.calls: list[str] = []

    def search(self, request: dict):
        self.calls.append(request["page_token"])
        if request["page_token"]:
            raise self.error_on_token
        return SimpleNamespace(pages=iter([self.page]))


class _FakeResumableManager:
    def __init__(self, saved_token: str | None):
        self._saved = saved_token
        self.saved_states: list[str] = []

    def can_resume(self) -> bool:
        return self._saved is not None

    def load_state(self) -> GoogleAdsResumeConfig | None:
        return GoogleAdsResumeConfig(page_token=self._saved) if self._saved is not None else None

    def save_state(self, data: GoogleAdsResumeConfig) -> None:
        self.saved_states.append(data.page_token)


class TestInvalidPageTokenDetection:
    def test_detects_invalid_page_token(self):
        exc = _google_ads_exception(RequestErrorEnum.RequestError.INVALID_PAGE_TOKEN)
        assert _is_invalid_page_token_error(exc) is True

    def test_ignores_other_request_errors(self):
        exc = _google_ads_exception(RequestErrorEnum.RequestError.RESOURCE_NAME_MISSING)
        assert _is_invalid_page_token_error(exc) is False

    def test_ignores_missing_failure(self):
        assert _is_invalid_page_token_error(SimpleNamespace(failure=None)) is False  # type: ignore[arg-type]


class TestSearchPageTokenResumption:
    def test_restarts_pagination_when_saved_page_token_expired(self):
        service = _FakeService(_single_page())
        manager = _FakeResumableManager(saved_token="STALE_TOKEN")

        tables = list(
            _search_as_arrow_tables(
                service=service,  # type: ignore[arg-type]
                customer_id="1234567890",
                query="SELECT campaign.name FROM campaign",
                table=_single_row_table(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            )
        )

        # The stale token was tried, rejected, then pagination restarted from the first page.
        assert service.calls == ["STALE_TOKEN", ""]
        # The stale token is cleared from saved state so a later resume won't reuse it.
        assert manager.saved_states == [""]
        # Rows are still yielded — the data was never lost.
        assert [t.to_pylist() for t in tables] == [[{"campaign_name": "Acme"}]]

    def test_other_google_ads_errors_propagate(self):
        service = _FakeService(
            _single_page(),
            error_on_token=_google_ads_exception(RequestErrorEnum.RequestError.RESOURCE_NAME_MISSING),
        )
        manager = _FakeResumableManager(saved_token="STALE_TOKEN")

        with pytest.raises(GoogleAdsException):
            list(
                _search_as_arrow_tables(
                    service=service,  # type: ignore[arg-type]
                    customer_id="1234567890",
                    query="SELECT campaign.name FROM campaign",
                    table=_single_row_table(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                )
            )

        # No restart attempt — the token was never reset.
        assert manager.saved_states == []

    def test_invalid_page_token_without_saved_state_does_not_loop(self):
        # Guards against an infinite restart loop: with no resumable token, an
        # INVALID_PAGE_TOKEN on the first (empty-token) request must propagate.
        always_failing = SimpleNamespace(
            calls=[],
        )

        def _always_raise(request: dict):
            always_failing.calls.append(request["page_token"])
            raise _google_ads_exception(RequestErrorEnum.RequestError.INVALID_PAGE_TOKEN)

        always_failing.search = _always_raise  # type: ignore[attr-defined]
        manager = _FakeResumableManager(saved_token=None)

        with pytest.raises(GoogleAdsException):
            list(
                _search_as_arrow_tables(
                    service=always_failing,  # type: ignore[arg-type]
                    customer_id="1234567890",
                    query="SELECT campaign.name FROM campaign",
                    table=_single_row_table(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                )
            )

        assert always_failing.calls == [""]
        assert manager.saved_states == []
