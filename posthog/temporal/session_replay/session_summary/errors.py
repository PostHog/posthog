from temporalio.exceptions import ApplicationError

from posthog.temporal.common.errors import NonReportableError

from ee.hogai.session_summaries.availability import CLOUD_ONLY_MESSAGE, session_summaries_environment_allowed


class SessionSummariesUnsupportedEnvironmentError(ApplicationError, NonReportableError):
    """Session summaries can't run on this deployment, and never will without a redeploy.

    `non_retryable` because no retry turns a self-hosted instance into a cloud one, and
    `NonReportableError` so the activity interceptor keeps it out of error tracking. Both
    matter: the group flow runs one activity per session, so a self-hosted instance with
    summarization switched on would otherwise report the same exception thousands of times
    per sweep, into whichever project the deployment's telemetry token points at.
    """

    def __init__(self) -> None:
        super().__init__(CLOUD_ONLY_MESSAGE, type="SessionSummariesUnsupportedEnvironment", non_retryable=True)


def raise_if_session_summaries_unsupported() -> None:
    if not session_summaries_environment_allowed():
        raise SessionSummariesUnsupportedEnvironmentError()
