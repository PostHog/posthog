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
    # When set, the activity persists the per-insight snapshot directly onto
    # SubscriptionDelivery.content_snapshot. Keeps multi-MB query_results off
    # the Temporal payload wire (~2 MiB gRPC cap). When unset (standalone
    # callers or pre-rollout workflow retries replaying old input shape), the
    # activity falls back to looking up the delivery row by workflow_id.
    delivery_id: typing.Optional[uuid.UUID] = None


@dataclasses.dataclass
class CreateExportAssetsResult:
    """Small metadata envelope for create_export_assets.

    Multi-MB snapshot data is written to Postgres from inside the activity via
    `delivery_id`, not returned here — the activity return payload crosses
    Temporal's ~2 MiB gRPC boundary and must stay size-bounded by construction.
    """

    exported_asset_ids: list[int]
    total_insight_count: int
    team_id: int = 0
    distinct_id: str = ""
    target_type: str = ""
    # Deprecated (TODO slug: subscriptions-patched-cleanup) — kept only so
    # that in-flight Temporal workflows (whose history contains an old-format
    # result) still deserialize on new workers during a rolling deploy. New
    # code does not populate this field. Remove in the second cleanup PR per
    # the sequence in workflows.py.
    insight_snapshots: typing.Optional[list[dict[str, typing.Any]]] = None


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
    """Patch a SubscriptionDelivery row. None on optional collections means leave the column unchanged.

    New code writes per-insight query results directly to Postgres from
    `create_export_assets` rather than shipping them back through this input
    (they can easily exceed Temporal's ~2 MiB payload cap). `content_snapshot`
    remains here only so that in-flight workflows from before the rollout can
    still replay successfully — their history carries a populated
    content_snapshot, and dropping the field would break deserialization.
    """

    delivery_id: uuid.UUID
    status: str
    exported_asset_ids: typing.Optional[list[int]] = None
    recipient_results: typing.Optional[list[dict[str, typing.Any]]] = None
    error: typing.Optional[dict[str, typing.Any]] = None
    change_summary: typing.Optional[str] = None
    finished: bool = False
    # Deprecated (TODO slug: subscriptions-patched-cleanup) — see docstring
    # above and cleanup sequence at top of workflows.py. Remove in the second
    # cleanup PR after task queue drain.
    content_snapshot: typing.Optional[dict[str, typing.Any]] = None


@dataclasses.dataclass
class SnapshotInsightsInputs:
    subscription_id: int
    team_id: int
    delivery_id: typing.Optional[str] = None
    summary_enabled: bool = False
    exported_asset_ids: typing.Optional[list[int]] = None


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
