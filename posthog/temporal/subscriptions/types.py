import uuid
import typing
import dataclasses

from posthog.slo.types import SloConfig

from ee.tasks.subscriptions.subscription_utils import DEFAULT_MAX_ASSET_COUNT


class DeliveryStatus:
    """Mirrors SubscriptionDelivery.Status choices for use in Temporal workflows.

    Plain string constants (not enum.Enum) for the same Temporal serialization
    reason as SubscriptionTriggerType.
    """

    STARTING = "starting"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SubscriptionTriggerType:
    """How a subscription delivery was triggered.

    Plain string constants (not enum.Enum) because Temporal's
    DefaultPayloadConverter mis-deserializes str enums as character lists.
    """

    SCHEDULED = "scheduled"  # Regular cron-based delivery
    TARGET_CHANGE = "target_change"  # Target changed (previous_value is the old target)
    MANUAL = "manual"  # User clicked "Test delivery"


@dataclasses.dataclass
class SubscriptionInfo:
    subscription_id: int
    team_id: int
    distinct_id: str
    next_delivery_date: typing.Optional[str] = None


@dataclasses.dataclass
class FetchDueSubscriptionsActivityInputs:
    buffer_minutes: int = 15

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "buffer_minutes": self.buffer_minutes,
        }


@dataclasses.dataclass
class CreateExportAssetsInputs:
    subscription_id: int
    max_asset_count: int = DEFAULT_MAX_ASSET_COUNT
    previous_value: typing.Optional[str] = None


@dataclasses.dataclass
class CreateExportAssetsResult:
    """Export batch metadata plus per-insight snapshots aligned with exported_asset_ids order."""

    exported_asset_ids: list[int]
    total_insight_count: int
    team_id: int = 0
    distinct_id: str = ""
    target_type: str = ""
    insight_snapshots: list[dict[str, typing.Any]] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class DeliverSubscriptionInputs:
    subscription_id: int
    exported_asset_ids: list[int]
    total_insight_count: int
    is_new_subscription_target: bool = False
    previous_value: typing.Optional[str] = None
    invite_message: typing.Optional[str] = None
    change_summary: typing.Optional[str] = None


@dataclasses.dataclass
class ProcessSubscriptionWorkflowInputs:
    subscription_id: int
    team_id: int = 0
    distinct_id: str = ""
    previous_value: typing.Optional[str] = None
    invite_message: typing.Optional[str] = None
    trigger_type: str = SubscriptionTriggerType.TARGET_CHANGE
    scheduled_at: typing.Optional[str] = None


@dataclasses.dataclass
class TrackedSubscriptionInputs:
    """Internal inputs for ProcessSubscriptionWorkflow with SLO tracking.

    Duplicates ProcessSubscriptionWorkflowInputs fields intentionally:
    Temporal deserializes by the declared parameter type, so SLO config
    must be on the type the workflow declares. Due to this "extending"
    ProcessSubscriptionWorkflow did not work.
    """

    subscription_id: int
    team_id: int = 0
    distinct_id: str = ""
    previous_value: typing.Optional[str] = None
    invite_message: typing.Optional[str] = None
    slo: SloConfig | None = None
    trigger_type: str = SubscriptionTriggerType.TARGET_CHANGE
    scheduled_at: typing.Optional[str] = None


RecipientResultStatus = typing.Literal["success", "failed", "partial"]


@dataclasses.dataclass
class RecipientResult:
    recipient: str
    status: RecipientResultStatus
    error: typing.Optional[dict[str, str]] = None  # {"message": str, "type": str}


@dataclasses.dataclass
class DeliverSubscriptionResult:
    recipient_results: list[RecipientResult] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class CreateDeliveryRecordInputs:
    subscription_id: int
    team_id: int
    trigger_type: str
    temporal_workflow_id: str
    idempotency_key: str
    scheduled_at: typing.Optional[str] = None


@dataclasses.dataclass
class UpdateDeliveryRecordInputs:
    """Patch a SubscriptionDelivery row. None on optional collections means leave the column unchanged."""

    delivery_id: uuid.UUID
    status: str
    exported_asset_ids: typing.Optional[list[int]] = None
    content_snapshot: typing.Optional[dict[str, typing.Any]] = None
    recipient_results: typing.Optional[list[dict[str, typing.Any]]] = None
    error: typing.Optional[dict[str, typing.Any]] = None
    finished: bool = False


@dataclasses.dataclass
class SnapshotInsightsInputs:
    subscription_id: int
    team_id: int
    delivery_id: typing.Optional[str] = None
    summary_enabled: bool = False


@dataclasses.dataclass
class SnapshotInsightsResult:
    summary_text: str | None = None


@dataclasses.dataclass
class ScheduleAllSubscriptionsWorkflowInputs:
    buffer_minutes: int = 15

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "buffer_minutes": self.buffer_minutes,
        }
