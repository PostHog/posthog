"""Build a tarball from a local agent project directory and deploy it to the
local stack.

Reads the project at the given path, tarballs it, uploads to MinIO (or whatever
object storage the dev stack is configured for), creates/updates an
AgentApplication + AgentApplicationRevision pointing at the bundle, and
promotes the revision live so agent-ingress + agent-runner can pick it up.

Intended for local dev only — production uses the presigned-POST flow in
deploys.start_deploy. This shortcut writes directly via object_storage.write
so we don't need a separate uploader process.
"""

from __future__ import annotations

import io
import hashlib
import tarfile
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from posthog.models.team import Team
from posthog.models.utils import uuid7
from posthog.storage import object_storage

from products.agent_stack.backend.enums import DeploymentStatus, RevisionState
from products.agent_stack.backend.models import AgentApplication, AgentApplicationRevision


def _build_tarball(project_dir: Path) -> tuple[bytes, str]:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        # arcname='' so paths inside the tar are relative to the project root
        # (matches what `loadProject(dir)` expects on the runner side).
        tar.add(str(project_dir), arcname="")
    payload = buf.getvalue()
    return payload, hashlib.sha256(payload).hexdigest()


class Command(BaseCommand):
    help = "Tarball a local agent project directory and deploy it to the local stack."

    def add_arguments(self, parser):
        parser.add_argument("project_dir", help="Path to an agent project root (containing .ass.yaml).")
        parser.add_argument("--team-id", type=int, default=1)
        parser.add_argument("--slug", required=True, help="Application slug to upsert.")
        parser.add_argument("--name", default=None, help="Application display name (defaults to slug).")
        parser.add_argument(
            "--description", default="Deployed via deploy_local_bundle", help="Application description."
        )

    def handle(self, *_args, **options) -> None:
        project_dir = Path(options["project_dir"]).resolve()
        if not (project_dir / ".ass.yaml").is_file():
            raise CommandError(f"{project_dir} is not an agent project (missing .ass.yaml)")

        team = Team.objects.get(id=options["team_id"])
        slug: str = options["slug"]
        name: str = options["name"] or slug

        payload, sha = _build_tarball(project_dir)

        app, app_created = AgentApplication.objects.get_or_create(
            team=team,
            slug=slug,
            defaults={"name": name, "description": options["description"]},
        )

        revision_id: UUID = uuid7()
        key = f"agent-bundles/{app.id}/{revision_id}.tar.gz"
        object_storage.object_storage_client().write(
            bucket=settings.AGENT_BUNDLES_S3_BUCKET,
            key=key,
            content=payload,
            extras={"ContentType": "application/gzip"},
        )

        revision = AgentApplicationRevision.objects.create(
            id=revision_id,
            team=team,
            application=app,
            state=RevisionState.READY,
            deployment_status=DeploymentStatus.DISABLED,
            bundle_s3_key=key,
            bundle_sha256=sha,
            bundle_size=len(payload),
            top_level_config={"version": "v1"},
        )

        # Demote any prior live revision before promoting the new one.
        AgentApplicationRevision.objects.filter(
            application=app,
            deployment_status=DeploymentStatus.LIVE,
        ).exclude(id=revision.id).update(deployment_status=DeploymentStatus.DISABLED, updated_at=timezone.now())
        revision.deployment_status = DeploymentStatus.LIVE
        revision.save(update_fields=["deployment_status", "updated_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"deployed {slug} ({'created' if app_created else 'updated'}): "
                f"revision={revision.id} key={key} sha256={sha[:12]} size={len(payload)}B"
            )
        )
