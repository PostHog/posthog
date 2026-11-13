from dataclasses import field
from typing import Literal
from uuid import UUID

from posthog.dataclasses import frozen


@frozen
class AccountAuditRequest:
    organization_id: UUID
    team_id: int | None = None
    reason: str
    skill_project: int
    skill_name: str


@frozen
class AccountAuditResult:
    status: Literal[
        "accepted",
        "skipped",
        "invalid",
        "skill_unavailable",
        "unauthorized",
        "forbidden",
        "conflict",
        "unavailable",
    ]
    task_run_id: UUID | None = None
    team_id: int | None = None


@frozen
class CreatedCredential:
    public_key_id: UUID
    # repr=False keeps the secret out of tracebacks and log lines that print the object.
    signing_secret: str = field(repr=False)
