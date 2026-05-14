"""
Exported enums for agent_stack.

If an enum appears in a contract dataclass field, it belongs here.
Internal-only constants (DB magic values, feature flags) stay in
the implementation (logic.py, models.py).
"""

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
