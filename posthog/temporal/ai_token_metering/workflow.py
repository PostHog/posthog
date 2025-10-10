import json
from datetime import datetime, timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, CancelledError

from posthog.temporal.ai_token_metering.activities import (
    aggregate_token_usage,
    check_stripe_enabled,
    get_or_create_metering_state,
    send_usage_to_stripe,
    update_processing_state,
)
from posthog.temporal.ai_token_metering.types import (
    AggregateTokenUsageInputs,
    CheckStripeEnabledInputs,
    GetOrCreateMeteringStateInputs,
    SendUsageToStripeInputs,
    TeamTokenMeteringInputs,
    UpdateProcessingStateInputs,
)
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger

logger = get_logger(__name__)

# Processing configuration
PROCESSING_INTERVAL_MINUTES = 30  # Process data every 30 minutes
BATCH_SIZE_HOURS = 1  # Process 1 hour of data at a time
SLEEP_BETWEEN_BATCHES_SECONDS = 2  # Sleep between batches to avoid overload
TRANSIENT_FAILURE_BASE_BACKOFF_SECONDS = 30
TRANSIENT_FAILURE_MAX_BACKOFF_SECONDS = 5 * 60


MAX_TRANSIENT_FAILURES_PER_RUN = 5


@workflow.defn(name="team-ai-token-metering")
class TeamAITokenMeteringWorkflow(PostHogWorkflow):
    """
    Workflow that processes AI token usage for a specific team.

    This workflow:
    1. Checks if Stripe is still enabled for the team
    2. Processes token usage in time windows
    3. Sends aggregated data to Stripe
    4. Updates processing state
    5. Exits once caught up so schedules can trigger the next run
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> TeamTokenMeteringInputs:
        """Parse inputs from the management command CLI."""
        if not inputs:
            raise ValueError("TeamAITokenMeteringWorkflow requires a JSON payload as the first CLI argument")

        try:
            loaded = json.loads(inputs[0])
        except json.JSONDecodeError as exc:
            raise ValueError("TeamAITokenMeteringWorkflow expects the first argument to be valid JSON") from exc

        raw_enabled_at = loaded.get("stripe_enabled_at")
        if raw_enabled_at is None:
            raise ValueError("TeamAITokenMeteringWorkflow expects `stripe_enabled_at` in the JSON payload")

        if isinstance(raw_enabled_at, str):
            candidate = raw_enabled_at.strip()
            if candidate.endswith("Z"):
                candidate = candidate.replace("Z", "+00:00")
            try:
                loaded["stripe_enabled_at"] = datetime.fromisoformat(candidate)
            except ValueError as exc:
                raise ValueError(
                    "TeamAITokenMeteringWorkflow expects `stripe_enabled_at` to be ISO 8601, "
                    "for example '2024-01-01T12:00:00+00:00'"
                ) from exc
        elif isinstance(raw_enabled_at, datetime):
            loaded["stripe_enabled_at"] = raw_enabled_at
        else:
            raise ValueError(
                "TeamAITokenMeteringWorkflow expects `stripe_enabled_at` to be an ISO 8601 string or datetime"
            )

        parsed_enabled_at = loaded["stripe_enabled_at"]
        if parsed_enabled_at.tzinfo is None:
            raise ValueError("TeamAITokenMeteringWorkflow expects `stripe_enabled_at` to include a timezone offset")

        return TeamTokenMeteringInputs(**loaded)

    @workflow.run
    async def run(self, inputs: TeamTokenMeteringInputs) -> None:
        """Main workflow execution."""
        workflow_logger = logger.bind(
            workflow_id=workflow.info().workflow_id,
            team_id=inputs.team_id,
        )
        workflow_logger.info(
            "Starting team AI token metering workflow",
            stripe_enabled_at=inputs.stripe_enabled_at,
        )

        # Get or create the metering state
        metering_state = await workflow.execute_activity(
            get_or_create_metering_state,
            GetOrCreateMeteringStateInputs(
                team_id=inputs.team_id,
                stripe_enabled_at=inputs.stripe_enabled_at,
            ),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        last_processed = metering_state.last_processed_timestamp
        consecutive_failures = 0

        try:
            while True:
                batch_start: datetime | None = None
                batch_end: datetime | None = None

                try:
                    is_enabled = await workflow.execute_activity(
                        check_stripe_enabled,
                        CheckStripeEnabledInputs(team_id=inputs.team_id),
                        start_to_close_timeout=timedelta(minutes=1),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )

                    if not is_enabled:
                        workflow_logger.info("Stripe integration disabled, stopping workflow")
                        return

                    now = workflow.now()
                    max_end_time = now - timedelta(minutes=5)

                    if last_processed >= max_end_time:
                        workflow_logger.debug(
                            "Caught up with processing, exiting run",
                            last_processed=last_processed,
                            max_end_time=max_end_time,
                        )
                        break

                    batch_start = last_processed
                    batch_end = min(
                        batch_start + timedelta(hours=BATCH_SIZE_HOURS),
                        max_end_time,
                    )

                    workflow_logger.info(
                        "Processing time range",
                        start=batch_start,
                        end=batch_end,
                    )

                    await workflow.execute_activity(
                        update_processing_state,
                        UpdateProcessingStateInputs(
                            team_id=inputs.team_id,
                            state_id=metering_state.state_id,
                            last_processed_timestamp=last_processed,
                            current_processing_start=batch_start,
                        ),
                        start_to_close_timeout=timedelta(minutes=1),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )

                    aggregation_result = await workflow.execute_activity(
                        aggregate_token_usage,
                        AggregateTokenUsageInputs(
                            team_id=inputs.team_id,
                            start_time=batch_start,
                            end_time=batch_end,
                        ),
                        start_to_close_timeout=timedelta(minutes=10),
                        retry_policy=RetryPolicy(
                            initial_interval=timedelta(seconds=10),
                            maximum_attempts=3,
                        ),
                        heartbeat_timeout=timedelta(minutes=1),
                    )

                    if aggregation_result.aggregations:
                        idempotency_key = f"team-{inputs.team_id}-{batch_start.isoformat()}-{batch_end.isoformat()}"

                        stripe_result = await workflow.execute_activity(
                            send_usage_to_stripe,
                            SendUsageToStripeInputs(
                                team_id=inputs.team_id,
                                aggregations=aggregation_result.aggregations,
                                time_range_start=batch_start,
                                time_range_end=batch_end,
                                idempotency_key=idempotency_key,
                            ),
                            start_to_close_timeout=timedelta(minutes=5),
                            retry_policy=RetryPolicy(
                                initial_interval=timedelta(seconds=30),
                                maximum_attempts=3,
                            ),
                        )

                        workflow_logger.info(
                            "Sent usage to Stripe",
                            customers_processed=stripe_result.customers_processed,
                            total_events=aggregation_result.total_events_processed,
                        )
                    else:
                        workflow_logger.info(
                            "No token usage found in time range",
                            start=batch_start,
                            end=batch_end,
                        )

                    await workflow.execute_activity(
                        update_processing_state,
                        UpdateProcessingStateInputs(
                            team_id=inputs.team_id,
                            state_id=metering_state.state_id,
                            last_processed_timestamp=batch_end,
                            current_processing_start=None,
                        ),
                        start_to_close_timeout=timedelta(minutes=1),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )

                    last_processed = batch_end
                    consecutive_failures = 0

                    if batch_end < max_end_time:
                        await workflow.sleep(SLEEP_BETWEEN_BATCHES_SECONDS)
                except ActivityError as activity_error:
                    consecutive_failures += 1
                    cause = getattr(activity_error, "cause", None)
                    failure_message = str(cause or activity_error)
                    backoff_seconds = min(
                        TRANSIENT_FAILURE_BASE_BACKOFF_SECONDS * consecutive_failures,
                        TRANSIENT_FAILURE_MAX_BACKOFF_SECONDS,
                    )
                    workflow_logger.warning(
                        "Transient activity failure; backing off",
                        error=failure_message,
                        failure_count=consecutive_failures,
                        backoff_seconds=backoff_seconds,
                    )

                    if consecutive_failures >= MAX_TRANSIENT_FAILURES_PER_RUN:
                        workflow_logger.exception(
                            "Exceeded transient failure threshold, failing workflow run",
                            failure_count=consecutive_failures,
                        )
                        raise

                    await workflow.sleep(backoff_seconds)
                    continue

        except CancelledError:
            workflow_logger.info("Workflow cancelled, cleaning up")
            # Mark the state as inactive when cancelled
            # Lifecycle hooks that cancel the workflow should mark the state inactive
            raise
        except Exception as e:
            workflow_logger.exception("Unexpected error in workflow", error=str(e))
            raise
        else:
            workflow_logger.info(
                "Completed metering run",
                last_processed_timestamp=last_processed,
            )
