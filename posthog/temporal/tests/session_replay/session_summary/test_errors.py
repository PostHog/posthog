import pytest

from django.test import override_settings

from temporalio.exceptions import ApplicationError

from posthog.temporal.common.errors import NonReportableError
from posthog.temporal.session_replay.session_summary.errors import (
    SessionSummariesUnsupportedEnvironmentError,
    raise_if_session_summaries_unsupported,
)


def test_unsupported_environment_error_is_non_retryable_and_non_reportable():
    error = SessionSummariesUnsupportedEnvironmentError()
    # Together these keep an off-cloud instance from retrying and reporting the same
    # exception once per session, per attempt.
    assert isinstance(error, ApplicationError)
    assert error.non_retryable is True
    assert isinstance(error, NonReportableError)


@pytest.mark.parametrize(
    "debug,cloud_deployment,expected_to_raise",
    [
        (False, None, True),
        (False, "", True),
        (False, "US", False),
        (True, None, False),
    ],
)
def test_raise_if_session_summaries_unsupported(debug: bool, cloud_deployment: str | None, expected_to_raise: bool):
    with override_settings(DEBUG=debug, CLOUD_DEPLOYMENT=cloud_deployment):
        if not expected_to_raise:
            raise_if_session_summaries_unsupported()
            return
        with pytest.raises(SessionSummariesUnsupportedEnvironmentError):
            raise_if_session_summaries_unsupported()
