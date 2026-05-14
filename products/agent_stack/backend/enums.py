"""Enums for agent_stack."""

from enum import StrEnum


class RevisionState(StrEnum):
    PENDING_UPLOAD = "pending_upload"
    UPLOADED = "uploaded"
    VALIDATING = "validating"
    READY = "ready"
    FAILED = "failed"


class DeploymentStatus(StrEnum):
    LIVE = "live"
    PREVIEW = "preview"
    DISABLED = "disabled"


class SessionState(StrEnum):
    """Retained for migration compatibility (0001_initial references this enum).
    Sessions are no longer modeled in Django — the runtime owns session state."""

    AVAILABLE = "available"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class SandboxState(StrEnum):
    PROVISIONING = "provisioning"
    READY = "ready"
    TERMINATING = "terminating"
    TERMINATED = "terminated"
