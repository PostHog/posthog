import json
import logging
import dataclasses
from datetime import timedelta

import structlog
from clickhouse_driver.errors import Error, ErrorCodes, NetworkError, SocketTimeoutError
from temporalio import activity, common, workflow
from temporalio.exceptions import ApplicationError

from posthog.errors import CH_TRANSIENT_ERRORS, QueryErrorCategory, classify_query_error
from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater

logger = structlog.get_logger()
logging.basicConfig(level=logging.INFO)

# Cluster trouble the next attempt can get past: a busy or unreachable ClickHouse host.
# The clickhouse_driver classes cover a host refused while the connection opens. The native socket
# classes cover a host that dies mid-read, after the connection is up: the driver re-raises those
# unwrapped (EOFError, ConnectionResetError and other ConnectionError subclasses, and a client-side
# TimeoutError), so no clickhouse_driver class or server code names them.
RETRIABLE_ERRORS = (*CH_TRANSIENT_ERRORS, NetworkError, SocketTimeoutError, ConnectionError, EOFError, TimeoutError)
# A socket timeout (209) or network error (210) raised server-side reaches this activity wrapped by
# sync_execute into a fresh dynamic class on every call, which no isinstance tuple can name, so those
# transient transport failures must be matched by code too.
RETRIABLE_CH_ERROR_CODES = (ErrorCodes.SOCKET_TIMEOUT, ErrorCodes.NETWORK_ERROR)


def _is_retriable_error(e: Exception) -> bool:
    if isinstance(e, RETRIABLE_ERRORS):
        return True
    if isinstance(e, Error) and getattr(e, "code", None) in RETRIABLE_CH_ERROR_CODES:
        return True
    # A busy cluster can answer with NO_FREE_CONNECTION (203) or SERVER_OVERLOADED (745), which
    # wrap_clickhouse_query_error leaves as a dynamic class no isinstance tuple names. The error
    # table marks every capacity error RATE_LIMITED, so match by that category, the busy-cluster
    # class this run's other retriable errors already sit in.
    return classify_query_error(e) == QueryErrorCategory.RATE_LIMITED


@dataclasses.dataclass
class RunQuotaLimitingInputs:
    pass


@dataclasses.dataclass
class RunQuotaLimitingAllOrgsInputs:
    pass


@dataclasses.dataclass
class QuotaLimitingResult:
    duration_s: float = 0.0
    orgs_total: int = 0
    orgs_processed: int = 0
    orgs_limited: int = 0
    orgs_suspended: int = 0


@activity.defn(name="run-quota-limiting-all-orgs")
async def run_quota_limiting_all_orgs(
    _inputs: RunQuotaLimitingAllOrgsInputs,
) -> QuotaLimitingResult:
    result = QuotaLimitingResult()
    async with Heartbeater() as heartbeater:
        try:
            from ee.billing.quota_limiting import update_all_orgs_billing_quotas

            def progress_callback(phase: str, progress: str, detail: str) -> None:
                heartbeater.details = (phase, progress, detail)

            @database_sync_to_async(thread_sensitive=True)
            def async_update_all_orgs_billing_quotas():
                return update_all_orgs_billing_quotas(progress_callback=progress_callback)

            run_result = await async_update_all_orgs_billing_quotas()
            result = QuotaLimitingResult(**run_result.stats)
        except ImportError:
            pass
        except Exception as e:
            capture_exception(e)
            # Raise exception without large context to avoid "Failure exceeds size limit".
            # `from None` suppresses the implicit __context__, which Temporal would otherwise
            # serialize as failure.cause and put the full original error back into history.
            raise ApplicationError(
                f"Quota limiting failed: {type(e).__name__}: {str(e)[:200]}...",
                # A deterministic failure repeats, so only retry the transient classes.
                non_retryable=not _is_retriable_error(e),
            ) from None
    return result


@workflow.defn(name="run-quota-limiting")
class RunQuotaLimitingWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> RunQuotaLimitingInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return RunQuotaLimitingInputs(**loaded)

    @workflow.run
    async def run(self, _inputs: RunQuotaLimitingInputs) -> QuotaLimitingResult:
        try:
            return await workflow.execute_activity(
                run_quota_limiting_all_orgs,
                RunQuotaLimitingAllOrgsInputs(),
                start_to_close_timeout=timedelta(hours=12),
                # start_to_close_timeout bounds each attempt; this bounds the whole retry sequence.
                # Without it the 3 attempts could hold the run open for ~36 hours while the schedule
                # skips every tick, leaving quota limits stale far longer than one attempt did before.
                schedule_to_close_timeout=timedelta(hours=12),
                retry_policy=common.RetryPolicy(
                    # A shard host that refuses connections stays down for minutes, so the waits
                    # (2 then 4 minutes) must outlast it and still fit the 15-minute schedule.
                    # Timeouts retry too, because non_retryable only covers ApplicationError, so a
                    # timed-out attempt can still write while the next one starts. That is accepted:
                    # a run recomputes and replaces the whole quota state, and the next tick
                    # corrects a stale write.
                    maximum_attempts=3,
                    initial_interval=timedelta(minutes=2),
                ),
                heartbeat_timeout=timedelta(minutes=2),
            )

        except Exception as e:
            capture_exception(e)
            raise
