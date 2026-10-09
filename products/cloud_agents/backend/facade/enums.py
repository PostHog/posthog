"""
Exported enums for cloud_agents.

If an enum appears in a contract dataclass field, it belongs here.
Internal-only constants (DB magic values, feature flags) stay in
the implementation (logic/, models.py).

No Django imports: use LabeledStrEnum or LabeledIntEnum, not
models.TextChoices, for an enum that backs model or serializer choices.
"""

from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum


class CloudAgentRunStatus(LabeledStrEnum):
    """`idle` has no sandbox and continues with a message. `done` is final and refuses a message."""

    QUEUED = "queued"
    RUNNING = "running"
    IDLE = "idle"
    DONE = "done"


class CloudAgentRunStatusReason(LabeledStrEnum):
    """Why a run is `idle` or `done`."""

    TURN_CLOSED = "turn_closed"
    PROVISION_FAILED = "provision_failed"
    UNEXPECTED_FAILURE = "unexpected_failure"
    TIMED_OUT = "timed_out"
    CREDIT_SPENT = "credit_spent"
    FINISHED = "finished"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class CloudAgentSessionStatus(LabeledStrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    ENDED = "ended"


class CloudAgentReasoningEffort(LabeledStrEnum):
    """The values that Tasks accepts. A model supports only some of them."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh", "Extra high"
    MAX = "max"
    ULTRACODE = "ultracode"


class InferenceMode(LabeledStrEnum):
    AUTO = "auto"
    OWN_SUBSCRIPTION = "own_subscription"
    POSTHOG = "posthog", "PostHog"


class InferenceBilling(LabeledStrEnum):
    POSTHOG = "posthog", "PostHog"
    OWN_SUBSCRIPTION = "own_subscription"


class BillingMode(LabeledStrEnum):
    BILLED = "billed"
    UNBILLED = "unbilled"


class CallerKind(LabeledStrEnum):
    API = "api", "API"
    APP = "app"
    INTERNAL = "internal"


class SizeName(LabeledStrEnum):
    """Sandbox sizes. The value is `<vCPU>x<memory in GiB>`."""

    S_1X2 = "1x2", "1 vCPU, 2 GiB"
    S_2X4 = "2x4", "2 vCPU, 4 GiB"
    S_2X8 = "2x8", "2 vCPU, 8 GiB"
    S_4X8 = "4x8", "4 vCPU, 8 GiB"
    S_4X16 = "4x16", "4 vCPU, 16 GiB"
    S_8X16 = "8x16", "8 vCPU, 16 GiB"
    S_8X32 = "8x32", "8 vCPU, 32 GiB"
    S_16X64 = "16x64", "16 vCPU, 64 GiB"


class UsageGroupBy(LabeledStrEnum):
    DAY = "day"
    PRESET = "preset"


@frozen
class SizeShape:
    vcpu: int
    memory_gib: int


def size_shape(size: SizeName) -> SizeShape:
    """Return the vCPU and memory for a size."""
    vcpu, memory_gib = SizeName(size).value.split("x")
    return SizeShape(vcpu=int(vcpu), memory_gib=int(memory_gib))
