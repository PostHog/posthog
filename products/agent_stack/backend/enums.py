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
