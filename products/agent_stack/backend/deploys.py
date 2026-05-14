"""Deploy state machine for agent_stack.

The four multi-step operations that drive a revision from upload to live:
start_deploy, complete_upload, promote, update_env.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from posthog.models.utils import uuid7
from posthog.storage import object_storage

from .enums import DeploymentStatus, RevisionState
from .models import AgentApplication, AgentApplicationRevision

# Hard upper bound on bundle size accepted by the presigned upload (50 MiB).
MAX_BUNDLE_SIZE = 50 * 1024 * 1024
PRESIGNED_URL_TTL_SECONDS = 15 * 60


class RevisionStateError(Exception):
    """A revision is in the wrong state for the requested transition."""


class StorageUnavailableError(Exception):
    """The object storage backend didn't return a presigned URL."""


def _bundle_key(application_id: UUID, revision_id: UUID) -> str:
    return f"agent-bundles/{application_id}/{revision_id}.tar.gz"


def start_deploy(
    *,
    application: AgentApplication,
    bundle_sha256: str,
    bundle_size: int,
    top_level_config: dict,
    created_by_id: int | None = None,
) -> tuple[AgentApplicationRevision, dict[str, Any]]:
    """Create a pending revision and return the presigned upload target.

    The presigned POST binds the upload to an exact size. The CLI-reported
    `bundle_sha256` is stored on the revision row as metadata for the future
    validator to re-verify; consistent with every other presigned-POST endpoint
    in the codebase, which doesn't enforce hashes at S3 upload time either.
    """
    if bundle_size <= 0 or bundle_size > MAX_BUNDLE_SIZE:
        raise ValueError(f"bundle_size must be 1..{MAX_BUNDLE_SIZE} bytes")
    if len(bundle_sha256) != 64:
        raise ValueError("bundle_sha256 must be a 64-char hex sha256")

    # Generate the id upfront so the bundle key can be set on the initial insert
    # — saves a follow-up UPDATE that would otherwise be needed to patch in the key.
    revision_id = uuid7()
    key = _bundle_key(application.id, revision_id)
    revision = AgentApplicationRevision.objects.create(
        id=revision_id,
        team_id=application.team_id,
        application=application,
        state=RevisionState.PENDING_UPLOAD,
        bundle_s3_key=key,
        bundle_sha256=bundle_sha256,
        bundle_size=bundle_size,
        top_level_config=top_level_config,
        created_by_id=created_by_id,
    )

    conditions: list[Any] = [
        {"bucket": settings.AGENT_BUNDLES_S3_BUCKET},
        ["content-length-range", bundle_size, bundle_size],
    ]
    presigned = object_storage.object_storage_client().get_presigned_post(
        bucket=settings.AGENT_BUNDLES_S3_BUCKET,
        file_key=key,
        conditions=conditions,
        expiration=PRESIGNED_URL_TTL_SECONDS,
    )
    if presigned is None:
        raise StorageUnavailableError("could not generate presigned upload URL")

    expires_at = timezone.now() + timedelta(seconds=PRESIGNED_URL_TTL_SECONDS)
    return revision, {
        "url": presigned["url"],
        "fields": presigned["fields"],
        "expires_at": expires_at,
    }


def complete_upload(*, revision: AgentApplicationRevision) -> AgentApplicationRevision:
    """v1 shortcut: transition the revision straight to state=ready."""
    with transaction.atomic():
        locked = AgentApplicationRevision.objects.select_for_update().get(pk=revision.pk)
        if locked.state not in (RevisionState.PENDING_UPLOAD, RevisionState.UPLOADED):
            raise RevisionStateError(f"revision {locked.id} in state {locked.state}, cannot complete upload")
        locked.state = RevisionState.READY
        locked.save(update_fields=["state", "updated_at"])
        return locked


def promote_revision(*, revision: AgentApplicationRevision) -> AgentApplicationRevision:
    """Atomically set the revision live, demote any prior live revision to disabled."""
    with transaction.atomic():
        locked = AgentApplicationRevision.objects.select_for_update().get(pk=revision.pk)
        if locked.state != RevisionState.READY:
            raise RevisionStateError(f"revision {locked.id} is state={locked.state}; only ready can be promoted")

        (
            AgentApplicationRevision.objects.filter(
                team_id=locked.team_id,
                application_id=locked.application_id,
                deployment_status=DeploymentStatus.LIVE,
            )
            .exclude(id=locked.id)
            .update(deployment_status=DeploymentStatus.DISABLED, updated_at=timezone.now())
        )
        locked.deployment_status = DeploymentStatus.LIVE
        locked.save(update_fields=["deployment_status", "updated_at"])
        return locked


def preview_revision(*, revision: AgentApplicationRevision) -> AgentApplicationRevision:
    """Mark a ready revision as preview. Previews coexist — no siblings demoted."""
    with transaction.atomic():
        locked = AgentApplicationRevision.objects.select_for_update().get(pk=revision.pk)
        if locked.state != RevisionState.READY:
            raise RevisionStateError(f"revision {locked.id} is state={locked.state}; only ready can be previewed")
        locked.deployment_status = DeploymentStatus.PREVIEW
        locked.save(update_fields=["deployment_status", "updated_at"])
        return locked


def disable_revision(*, revision: AgentApplicationRevision) -> AgentApplicationRevision:
    """Force a revision off any traffic role. Allowed from any state — useful for killing broken revisions."""
    with transaction.atomic():
        locked = AgentApplicationRevision.objects.select_for_update().get(pk=revision.pk)
        locked.deployment_status = DeploymentStatus.DISABLED
        locked.save(update_fields=["deployment_status", "updated_at"])
        return locked


def update_env(*, application: AgentApplication, env: str) -> AgentApplication:
    """Replace encrypted_env. Plaintext flows in via this function only."""
    application.encrypted_env = env
    application.save(update_fields=["encrypted_env", "updated_at"])
    return application
