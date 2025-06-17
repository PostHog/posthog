from collections.abc import Generator
from ee.hogai.utils.asgi import SyncIterableToAsync
from ee.session_recordings.session_summary.summarize_session import ExtraSummaryContext
from posthog.models.team.team import Team
from posthog.settings import SERVER_GATEWAY_INTERFACE
from posthog.temporal.ai.session_summary.summarize_session import execute_summarize_session


def stream_recording_summary(
    session_id: str,
    user_pk: int,
    team: Team,
    extra_summary_context: ExtraSummaryContext | None = None,
    local_reads_prod: bool = False,
) -> SyncIterableToAsync | Generator[str, None, None]:
    if SERVER_GATEWAY_INTERFACE == "ASGI":
        return _astream(
            session_id=session_id,
            user_pk=user_pk,
            team=team,
            extra_summary_context=extra_summary_context,
            local_reads_prod=local_reads_prod,
        )
    return execute_summarize_session(
        session_id=session_id,
        user_pk=user_pk,
        team=team,
        extra_summary_context=extra_summary_context,
        local_reads_prod=local_reads_prod,
    )


def _astream(
    session_id: str,
    user_pk: int,
    team: Team,
    extra_summary_context: ExtraSummaryContext | None = None,
    local_reads_prod: bool = False,
) -> SyncIterableToAsync:
    return SyncIterableToAsync(
        execute_summarize_session(
            session_id=session_id,
            user_pk=user_pk,
            team=team,
            extra_summary_context=extra_summary_context,
            local_reads_prod=local_reads_prod,
        )
    )
