import dataclasses
from datetime import datetime
from typing import Optional


@dataclasses.dataclass
class TeamTokenMeteringInputs:
    """Inputs for the team-specific token metering workflow."""

    team_id: int
    stripe_enabled_at: datetime  # Start processing from this timestamp


@dataclasses.dataclass
class TokenAggregation:
    """Represents aggregated token usage for a specific Stripe customer."""

    stripe_customer_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclasses.dataclass
class CheckStripeEnabledInputs:
    """Inputs for checking if Stripe is enabled for a team."""

    team_id: int


@dataclasses.dataclass
class GetOrCreateMeteringStateInputs:
    """Inputs for getting or creating the metering state."""

    team_id: int
    stripe_enabled_at: datetime


@dataclasses.dataclass
class MeteringStateOutput:
    """Output from getting/creating metering state."""

    state_id: str
    last_processed_timestamp: datetime
    stripe_enabled_at: datetime
    is_new: bool


@dataclasses.dataclass
class AggregateTokenUsageInputs:
    """Inputs for aggregating token usage from events."""

    team_id: int
    start_time: datetime
    end_time: datetime


@dataclasses.dataclass
class AggregateTokenUsageOutput:
    """Output from token usage aggregation."""

    aggregations: list[TokenAggregation]
    total_events_processed: int
    time_range_start: datetime
    time_range_end: datetime


@dataclasses.dataclass
class SendUsageToStripeInputs:
    """Inputs for sending usage data to Stripe."""

    team_id: int
    aggregations: list[TokenAggregation]
    time_range_start: datetime
    time_range_end: datetime
    idempotency_key: str


@dataclasses.dataclass
class SendUsageToStripeOutput:
    """Output from sending usage to Stripe."""

    customers_processed: int


@dataclasses.dataclass
class UpdateProcessingStateInputs:
    """Inputs for updating the processing state."""

    team_id: int
    state_id: str
    last_processed_timestamp: datetime
    current_processing_start: Optional[datetime] = None
