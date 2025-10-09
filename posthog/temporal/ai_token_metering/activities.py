from django.db import close_old_connections

from temporalio import activity

from posthog.models.ai_token_metering import AITokenMeteringState
from posthog.temporal.ai_token_metering.types import (
    AggregateTokenUsageInputs,
    AggregateTokenUsageOutput,
    CheckStripeEnabledInputs,
    GetOrCreateMeteringStateInputs,
    MeteringStateOutput,
    SendUsageToStripeInputs,
    SendUsageToStripeOutput,
    TokenAggregation,
    UpdateProcessingStateInputs,
)
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

logger = get_logger(__name__)


@activity.defn
async def check_stripe_enabled(inputs: CheckStripeEnabledInputs) -> bool:
    """Check if Stripe integration is enabled for the team."""
    async with Heartbeater():
        close_old_connections()

        try:
            # TODO: Implement actual Stripe integration check
            # For now, we'll mock this - you'll need to implement the actual check
            # based on how Stripe integrations are stored in your system
            logger.info(
                "Checking Stripe integration status",
                team_id=inputs.team_id,
            )

            # Mock implementation - replace with actual check
            # Example: team = Team.objects.get(id=inputs.team_id)
            # return team.has_stripe_integration()

            return True  # TODO: Replace with actual implementation

        except Exception as e:
            logger.exception(
                "Failed to check Stripe integration status",
                team_id=inputs.team_id,
                error=str(e),
            )
            raise


@activity.defn
async def get_or_create_metering_state(inputs: GetOrCreateMeteringStateInputs) -> MeteringStateOutput:
    """Get or create the metering state for a team."""
    async with Heartbeater():
        close_old_connections()

        try:
            from django.db import transaction

            from asgiref.sync import sync_to_async

            # Look for an active metering state
            @sync_to_async
            @transaction.atomic
            def get_or_create_state():
                state = AITokenMeteringState.objects.filter(
                    team_id=inputs.team_id,
                    is_active=True,
                ).first()

                if state:
                    # State already exists (likely created when the Stripe enable hook launched the workflow)
                    return state, False

                # This should rarely happen now since lifecycle hooks create the state
                # But keeping it as a fallback for manual workflow starts or edge cases
                state = AITokenMeteringState.objects.create(
                    team_id=inputs.team_id,
                    stripe_enabled_at=inputs.stripe_enabled_at,
                    last_processed_timestamp=inputs.stripe_enabled_at,
                    is_active=True,
                    # workflow_id will be null here, but that's OK for manual starts
                )
                return state, True

            state, is_new = await get_or_create_state()

            if is_new:
                logger.info(
                    "Created new metering state",
                    team_id=inputs.team_id,
                    state_id=str(state.id),
                    stripe_enabled_at=inputs.stripe_enabled_at,
                )
            else:
                logger.info(
                    "Found existing metering state",
                    team_id=inputs.team_id,
                    state_id=str(state.id),
                    last_processed=state.last_processed_timestamp,
                )

            return MeteringStateOutput(
                state_id=str(state.id),
                last_processed_timestamp=state.last_processed_timestamp,
                stripe_enabled_at=state.stripe_enabled_at,
                is_new=is_new,
            )

        except Exception as e:
            logger.exception(
                "Failed to get or create metering state",
                team_id=inputs.team_id,
                error=str(e),
            )
            raise


@activity.defn
async def aggregate_token_usage(inputs: AggregateTokenUsageInputs) -> AggregateTokenUsageOutput:
    """Aggregate token usage from ClickHouse events."""
    async with Heartbeater():
        close_old_connections()

        try:
            logger.info(
                "Aggregating token usage",
                team_id=inputs.team_id,
                start_time=inputs.start_time,
                end_time=inputs.end_time,
            )

            # Query to aggregate token usage by stripe_customer_id
            query = """
                WITH
                    replaceRegexpAll(nullIf(JSONExtractRaw(properties, 'stripe_customer_id'), ''), '^"|"$', '') AS raw_customer_id,
                    nullIf(trim(BOTH ' ' FROM raw_customer_id), '') AS cleaned_customer_id,
                    if(lowerUTF8(cleaned_customer_id) = 'null', NULL, cleaned_customer_id) AS stripe_customer_id,
                    replaceRegexpAll(nullIf(JSONExtractRaw(properties, '$ai_input_tokens'), ''), '^"|"$', '') AS raw_input_tokens,
                    replaceRegexpAll(nullIf(JSONExtractRaw(properties, '$ai_output_tokens'), ''), '^"|"$', '') AS raw_output_tokens,
                    accurateCastOrNull(
                        if(lowerUTF8(raw_input_tokens) = 'null', NULL, raw_input_tokens),
                        'Float64'
                    ) AS input_token_value,
                    accurateCastOrNull(
                        if(lowerUTF8(raw_output_tokens) = 'null', NULL, raw_output_tokens),
                        'Float64'
                    ) AS output_token_value
                SELECT
                    stripe_customer_id,
                    sumIf(coalesce(input_token_value, 0), stripe_customer_id IS NOT NULL) AS input_tokens,
                    sumIf(coalesce(output_token_value, 0), stripe_customer_id IS NOT NULL) AS output_tokens,
                    countIf(stripe_customer_id IS NOT NULL) AS event_count
                FROM events
                WHERE
                    team_id = %(team_id)s
                    AND event IN ('$ai_generation', '$ai_embedding')
                    AND timestamp >= %(start_time)s
                    AND timestamp < %(end_time)s
                GROUP BY stripe_customer_id
                HAVING
                    stripe_customer_id IS NOT NULL
                    AND (input_tokens > 0 OR output_tokens > 0)
                FORMAT JSONEachRow
            """

            query_params = {
                "team_id": inputs.team_id,
                "start_time": inputs.start_time,
                "end_time": inputs.end_time,
            }

            aggregations = []
            total_events = 0

            async with get_client(team_id=inputs.team_id) as client:
                async for row in client.stream_query_as_jsonl(
                    query,
                    query_parameters=query_params,
                ):
                    stripe_customer_id = row.get("stripe_customer_id")
                    if not stripe_customer_id:
                        continue

                    input_tokens_value = row.get("input_tokens", 0) or 0
                    output_tokens_value = row.get("output_tokens", 0) or 0

                    input_tokens = int(round(float(input_tokens_value)))
                    output_tokens = int(round(float(output_tokens_value)))
                    if input_tokens <= 0 and output_tokens <= 0:
                        continue
                    event_count = int(row.get("event_count", 0) or 0)

                    aggregations.append(
                        TokenAggregation(
                            stripe_customer_id=stripe_customer_id,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            total_tokens=input_tokens + output_tokens,
                        )
                    )
                    total_events += event_count

            logger.info(
                "Token usage aggregation complete",
                team_id=inputs.team_id,
                customers_found=len(aggregations),
                total_events=total_events,
                time_range_hours=(inputs.end_time - inputs.start_time).total_seconds() / 3600,
            )

            return AggregateTokenUsageOutput(
                aggregations=aggregations,
                total_events_processed=total_events,
                time_range_start=inputs.start_time,
                time_range_end=inputs.end_time,
            )

        except Exception as e:
            logger.exception(
                "Failed to aggregate token usage",
                team_id=inputs.team_id,
                error=str(e),
            )
            raise


@activity.defn
async def send_usage_to_stripe(inputs: SendUsageToStripeInputs) -> SendUsageToStripeOutput:
    """Send aggregated usage data to Stripe."""
    async with Heartbeater():
        close_old_connections()

        try:
            logger.info(
                "Sending usage to Stripe",
                team_id=inputs.team_id,
                customers_count=len(inputs.aggregations),
                idempotency_key=inputs.idempotency_key,
            )

            # TODO: Implement actual Stripe API calls
            # This is where you'll make requests to Stripe's Usage Records API
            # Example structure:
            # for aggregation in inputs.aggregations:
            #     stripe.SubscriptionItem.create_usage_record(
            #         subscription_item="si_xxx",  # Get from customer mapping
            #         quantity=aggregation.total_tokens,
            #         timestamp=inputs.time_range_end,
            #         action="set",  # or "increment"
            #         idempotency_key=f"{inputs.idempotency_key}-{aggregation.stripe_customer_id}",
            #     )

            # Log what would be sent (for development)
            for aggregation in inputs.aggregations:
                logger.info(
                    "Would send to Stripe",
                    team_id=inputs.team_id,
                    stripe_customer_id=aggregation.stripe_customer_id,
                    input_tokens=aggregation.input_tokens,
                    output_tokens=aggregation.output_tokens,
                    total_tokens=aggregation.total_tokens,
                    idempotency_key=f"{inputs.idempotency_key}-{aggregation.stripe_customer_id}",
                )

            return SendUsageToStripeOutput(
                customers_processed=len(inputs.aggregations),
            )

        except Exception as e:
            logger.exception(
                "Failed to send usage to Stripe",
                team_id=inputs.team_id,
                error=str(e),
            )
            raise


@activity.defn
async def update_processing_state(inputs: UpdateProcessingStateInputs) -> None:
    """Update the processing state after successful processing."""
    async with Heartbeater():
        close_old_connections()

        try:
            from asgiref.sync import sync_to_async

            @sync_to_async
            def update_state():
                AITokenMeteringState.objects.filter(
                    id=inputs.state_id,
                ).update(
                    last_processed_timestamp=inputs.last_processed_timestamp,
                    current_processing_start=inputs.current_processing_start,
                )

            await update_state()

            logger.info(
                "Updated processing state",
                team_id=inputs.team_id,
                state_id=inputs.state_id,
                last_processed=inputs.last_processed_timestamp,
            )

        except Exception as e:
            logger.exception(
                "Failed to update processing state",
                team_id=inputs.team_id,
                state_id=inputs.state_id,
                error=str(e),
            )
            raise
