"""Frozen request / response contracts shared with the Build/Infra and GitHub streams.

These are FROZEN at hour 1 of the hackathon. The Build/Infra stream consumes
`BuildInput` as the Temporal workflow's input payload, and posts back to the
internal API using the `TransitionRequest` / `EventRequest` shapes. The GitHub
stream emits `CommitMetadata` after resolving a branch HEAD.

Keep these as plain dataclasses with no Django imports — they cross process
boundaries (the Temporal worker is its own pod) and must serialize cleanly
through JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from .status import Status
from .trigger import ErrorStep, TriggerKind


@dataclass(frozen=True)
class CommitMetadata:
    """Returned by the GitHub adapter after resolving a branch HEAD or a SHA."""

    sha: str
    message: str
    author_name: str
    author_email: str
    branch: str


@dataclass(frozen=True)
class BuildInput:
    """Payload the API hands to the Temporal worker when starting a build.

    The worker owns everything past this point — clone, install, build, publish.
    `github_access_token` is the short-lived installation token the API resolved
    from the project's `posthog.Integration` row (kind=github). It travels with
    the payload (encrypted in transit by Temporal) so the worker can authenticate
    against GitHub without a second roundtrip to the API. Tokens last ~1h —
    sufficient for hackathon-scale builds; long-running builds would need the
    worker to refresh through the integration framework instead.
    """

    deployment_id: UUID
    project_id: UUID
    team_id: int
    repo_url: str
    branch: str
    commit_sha: str
    github_access_token: str | None
    build_command: str | None
    output_dir: str
    framework: str | None
    inject_posthog_snippet: bool
    cloudflare_project_name: str
    trigger_kind: TriggerKind


@dataclass(frozen=True)
class TransitionRequest:
    """Body of POST /api/internal/deployments/{id}/transitions/."""

    status: Status
    cloudflare_deployment_id: str | None = None
    deployment_url: str | None = None
    error_message: str | None = None
    error_step: ErrorStep | None = None
    started_at_iso: str | None = None
    finished_at_iso: str | None = None


@dataclass(frozen=True)
class EventRequest:
    """Body of POST /api/internal/deployments/{id}/events/."""

    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
