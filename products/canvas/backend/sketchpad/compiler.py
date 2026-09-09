import json
import shutil
import subprocess
from datetime import timedelta
from functools import lru_cache, partial
from hashlib import sha256
from uuid import uuid4

from django.db import transaction
from django.db.models import QuerySet
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone

from celery import shared_task
from pydantic import BaseModel, ConfigDict, Field

from posthog.tasks.utils import CeleryQueue

from products.canvas.backend.contract import CANVAS_BUILDER_DIR
from products.canvas.backend.facade.enums import SketchpadRecordKind
from products.canvas.backend.models import Sketchpad, SketchpadCompileJob, SketchpadRecord

MAX_BATCH_SIZE = 256
MAX_BATCH_BYTES = 4 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024


class CompiledFragment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(default="", max_length=4 * 1024 * 1024)
    imports: list[str] = Field(default_factory=list, max_length=32)
    error: str | None = Field(default=None, max_length=10_000)


@lru_cache(maxsize=1)
def compiler_version() -> str:
    digest = sha256()
    for name in ("sketchpad.mjs", "manifest.json", "package-lock.json"):
        digest.update((CANVAS_BUILDER_DIR / name).read_bytes())
    return digest.hexdigest()


def active_sources(records: QuerySet[SketchpadRecord]) -> QuerySet[SketchpadRecord, str]:
    return (
        records.filter(kind=SketchpadRecordKind.FRAGMENT)
        .annotate(ref=KeyTextTransform("codeRef", "value"))
        .values_list("ref", flat=True)
    )


def compiled_fragments(sketchpad: Sketchpad, refs: list[str]) -> dict[str, CompiledFragment]:
    records = SketchpadRecord.objects.for_team(sketchpad.team_id).filter(sketchpad=sketchpad)
    version = compiler_version()
    ready: dict[str, CompiledFragment] = {}
    size = 0
    cached = records.filter(kind=SketchpadRecordKind.COMPILED, key__in=refs, value__compiler=version)
    for row in cached.iterator(chunk_size=8):
        artifact = CompiledFragment.model_validate(row.value["artifact"])
        size += len(artifact.code.encode())
        if size > MAX_OUTPUT_BYTES:
            break
        ready[row.key] = artifact
    missing = set(refs) - ready.keys()
    jobs = SketchpadCompileJob.objects.for_team(sketchpad.team_id).filter(sketchpad=sketchpad)
    if not missing or jobs.filter(expires_at__gt=timezone.now()).exists():
        return ready
    with transaction.atomic():
        locked = Sketchpad.objects.for_team(sketchpad.team_id).select_for_update().get(pk=sketchpad.pk, deleted=False)
        if jobs.filter(expires_at__gt=timezone.now()).exists():
            return ready
        missing -= set(cached.values_list("key", flat=True))
        queued = list(
            records.filter(kind=SketchpadRecordKind.SOURCE, key__in=missing)
            .filter(key__in=active_sources(records))
            .values_list("key", flat=True)[:MAX_BATCH_SIZE]
        )
        if not queued:
            return ready
        job = str(uuid4())
        jobs.update_or_create(
            team_id=sketchpad.team_id,
            sketchpad=sketchpad,
            defaults={
                "job": job,
                "refs": queued,
                "requested_seq": locked.head_seq,
                "compiler_version": version,
                "expires_at": timezone.now() + timedelta(seconds=120),
                "started_at": None,
            },
        )
        transaction.on_commit(
            partial(
                compile_sketchpad_fragments.apply_async,
                args=[sketchpad.team_id, str(sketchpad.pk), job, version],
                expires=30,
            )
        )
    return ready


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value, soft_time_limit=60, time_limit=75)
def compile_sketchpad_fragments(team_id: int, sketchpad_id: str, job: str, version: str) -> None:
    if version != compiler_version():
        return
    records = SketchpadRecord.objects.for_team(team_id).filter(sketchpad_id=sketchpad_id)
    jobs = SketchpadCompileJob.objects.for_team(team_id).filter(sketchpad_id=sketchpad_id, job=job)
    with transaction.atomic():
        if not Sketchpad.objects.for_team(team_id).select_for_update().filter(pk=sketchpad_id, deleted=False).exists():
            return
        queued = jobs.filter(expires_at__gt=timezone.now() + timedelta(seconds=75), started_at__isnull=True).first()
        if queued is None:
            return
        queued.started_at = timezone.now()
        queued.save(update_fields=["started_at", "updated_at"])
    sources: dict[str, str] = {}
    size = 0
    rows = records.filter(kind=SketchpadRecordKind.SOURCE, key__in=queued.refs).filter(key__in=active_sources(records))
    for row in rows.iterator(chunk_size=8):
        size += len(row.value.encode())
        if size > MAX_BATCH_BYTES:
            break
        sources[row.key] = row.value
    executable = shutil.which("node")
    if not executable:
        raise RuntimeError("Node is not installed for the Sketchpad compiler.")
    process = subprocess.run(
        [executable, "--max-old-space-size=256", str(CANVAS_BUILDER_DIR / "sketchpad.mjs")],
        input=json.dumps({"project": sources}, separators=(",", ":")),
        capture_output=True,
        text=True,
        timeout=45,
        check=True,
        cwd=CANVAS_BUILDER_DIR,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "NODE_ENV": "production"},
    )
    results = {ref: CompiledFragment.model_validate(value) for ref, value in json.loads(process.stdout).items()}
    with transaction.atomic():
        if (
            not Sketchpad.objects.for_team(team_id).select_for_update().filter(pk=sketchpad_id, deleted=False).exists()
            or not jobs.exists()
        ):
            return
        active = set(active_sources(records))
        records.bulk_create(
            [
                SketchpadRecord(
                    team_id=team_id,
                    sketchpad_id=sketchpad_id,
                    kind=SketchpadRecordKind.COMPILED,
                    key=ref,
                    value={"compiler": version, "artifact": artifact.model_dump()},
                )
                for ref, artifact in results.items()
                if ref in active
            ],
            update_conflicts=True,
            unique_fields=["sketchpad", "kind", "key"],
            update_fields=["value", "updated_at"],
        )
        jobs.delete()
