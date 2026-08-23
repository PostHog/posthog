"""Git bundle store for organization context wikis.

One bare Git repo per organization, serialized as a `git bundle` in object
storage, with the current head sha in Postgres (`ContextLayerConfig.head_sha`)
as a compare-and-swap pointer. Every writer follows the same protocol: acquire
the per-org Redis lock, download the bundle, clone to tmp, apply commits, lint,
upload the new bundle, CAS the head, release. Readers never take the lock.
"""

from __future__ import annotations

import uuid
import shutil
import tempfile
import threading
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import structlog
from redis.exceptions import RedisError

from posthog.dataclasses import frozen
from posthog.redis import get_client
from posthog.storage import object_storage

from products.context_layer.backend.models import ContextLayerConfig
from products.context_layer.backend.repo_lint import lint_repo
from products.context_layer.backend.scaffold import write_default_structure

logger = structlog.get_logger(__name__)

BUNDLE_KEY_PREFIX = "context_layer"
DEFAULT_BRANCH = "main"
LOCK_TTL_MS = 60_000
LOCK_RENEW_INTERVAL_SECONDS = 20.0
GIT_TIMEOUT_SECONDS = 60
COMMITTER_NAME = "PostHog Context Layer"
COMMITTER_EMAIL = "context-layer@posthog.com"


class ContextLayerStoreError(Exception):
    pass


class RepoNotFoundError(ContextLayerStoreError):
    """The organization has no context layer repo (no config row or no bundle)."""


class RepoLockUnavailableError(ContextLayerStoreError):
    """Another writer holds the per-org lock; retry later."""


class HeadMovedError(ContextLayerStoreError):
    """The head sha moved underneath a landing writer, twice."""


class PurgeIncompleteError(ContextLayerStoreError):
    """A purge rewrote the history but could not remove every old bundle, so
    sensitive content may still be readable in object storage."""


class LintFailedError(ContextLayerStoreError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("wiki structure lint failed: " + "; ".join(errors))
        self.errors = errors


@frozen
class RepoCheckout:
    """A temporary working clone of an organization's wiki."""

    path: Path
    head_sha: str


@frozen
class CommitAuthor:
    name: str
    email: str


SYSTEM_AUTHOR = CommitAuthor(name=COMMITTER_NAME, email=COMMITTER_EMAIL)


def bundle_prefix(organization_id: uuid.UUID | str) -> str:
    return f"{BUNDLE_KEY_PREFIX}/{organization_id}/bundles/"


def bundle_key(organization_id: uuid.UUID | str, head_sha: str) -> str:
    return f"{bundle_prefix(organization_id)}{head_sha}.bundle"


def _lock_key(organization_id: uuid.UUID | str) -> str:
    return f"context_layer:repo:{organization_id}"


# Renewal and release must check ownership and act atomically: after TTL expiry
# another writer may hold the key, and a plain get-then-expire/delete could
# extend or drop that writer's lock. Same scripts as posthog/api/query_coalescer.py.
_RENEW_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("pexpire", KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""


@contextmanager
def repo_writer_lock(organization_id: uuid.UUID | str) -> Iterator[None]:
    """Per-org writer lock: SET NX PX with a heartbeat, so a crashed writer
    frees the org within `LOCK_TTL_MS` while a slow live writer keeps it."""
    client = get_client()
    key = _lock_key(organization_id)
    token = uuid.uuid4().hex
    if not client.set(key, token, nx=True, px=LOCK_TTL_MS):
        raise RepoLockUnavailableError(f"another writer holds the context layer lock for {organization_id}")

    stop = threading.Event()

    def renew() -> None:
        while not stop.wait(LOCK_RENEW_INTERVAL_SECONDS):
            try:
                client.eval(_RENEW_LOCK_SCRIPT, 1, key, token, LOCK_TTL_MS)
            except RedisError:
                break

    heartbeat = threading.Thread(target=renew, name=f"context-layer-lock-{organization_id}", daemon=True)
    heartbeat.start()
    try:
        yield
    finally:
        stop.set()
        heartbeat.join(timeout=1)
        # The write has already landed by the time we release; a Redis error here
        # must not mask the result. The TTL frees the key if Redis stays down.
        try:
            client.eval(_RELEASE_LOCK_SCRIPT, 1, key, token)
        except RedisError:
            logger.warning("context_layer.repo_writer_lock.release_failed", organization_id=str(organization_id))


def _run_git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            f"user.name={COMMITTER_NAME}",
            "-c",
            f"user.email={COMMITTER_EMAIL}",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise ContextLayerStoreError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _download_bundle(organization_id: uuid.UUID | str, head_sha: str, into: Path) -> Path:
    bundle_bytes = object_storage.read_bytes(bundle_key(organization_id, head_sha), missing_ok=True)
    if bundle_bytes is None:
        raise RepoNotFoundError(f"no bundle at head {head_sha} for organization {organization_id}")
    bundle_path = into / "repo.bundle"
    bundle_path.write_bytes(bundle_bytes)
    return bundle_path


def _upload_bundle(organization_id: uuid.UUID | str, head_sha: str, workdir: Path) -> None:
    bundle_path = workdir.parent / f"{head_sha}.bundle"
    _run_git(["bundle", "create", str(bundle_path), "--all"], cwd=workdir)
    object_storage.write_from_file(bundle_key(organization_id, head_sha), str(bundle_path))


def _prune_bundles_except(organization_id: uuid.UUID | str, keep_head: str) -> None:
    """Delete every stored bundle for the organization except `keep_head`'s.

    Each landed head keeps its own bundle, so old bundles hold the history a
    purge is meant to erase. This must run while holding the writer lock, with
    `keep_head` read under that lock, so it never deletes the live head's bundle.
    Anything short of a clean listing and delete raises, so a purge never reports
    success while old bundles remain readable.
    """
    keep_key = bundle_key(organization_id, keep_head)
    existing = object_storage.list_objects(bundle_prefix(organization_id))
    if existing is None:
        raise PurgeIncompleteError(f"could not list bundles to purge for organization {organization_id}")
    stale = [key for key in existing if key != keep_key]
    if not stale:
        return
    failed = object_storage.delete_objects(stale)
    if failed:
        raise PurgeIncompleteError(
            f"could not delete {len(failed)} old bundle(s) while purging organization {organization_id}"
        )


def _clone_from_bundle(bundle_path: Path, workdir: Path) -> None:
    _run_git(["clone", "--quiet", str(bundle_path), str(workdir)], cwd=bundle_path.parent)
    _run_git(["checkout", "--quiet", DEFAULT_BRANCH], cwd=workdir)


def _commit_all(workdir: Path, message: str, author: CommitAuthor) -> str:
    _run_git(["add", "--all"], cwd=workdir)
    _run_git(["commit", "--quiet", "--author", f"{author.name} <{author.email}>", "-m", message], cwd=workdir)
    return _run_git(["rev-parse", "HEAD"], cwd=workdir)


def _has_changes(workdir: Path) -> bool:
    return bool(_run_git(["status", "--porcelain"], cwd=workdir))


def _lint_or_raise(workdir: Path) -> None:
    errors = lint_repo(workdir)
    if errors:
        raise LintFailedError(errors)


def get_config(organization_id: uuid.UUID | str) -> ContextLayerConfig:
    try:
        return ContextLayerConfig.objects.get(organization_id=organization_id)
    except ContextLayerConfig.DoesNotExist:
        raise RepoNotFoundError(f"organization {organization_id} has no context layer") from None


@contextmanager
def checkout_repo(organization_id: uuid.UUID | str) -> Iterator[RepoCheckout]:
    """Read-side checkout of the current head into a temporary working tree."""
    config = get_config(organization_id)
    with tempfile.TemporaryDirectory(prefix="context-layer-") as tmp:
        tmpdir = Path(tmp)
        bundle_path = _download_bundle(organization_id, config.head_sha, tmpdir)
        workdir = tmpdir / "repo"
        _clone_from_bundle(bundle_path, workdir)
        yield RepoCheckout(path=workdir, head_sha=config.head_sha)


def initialize_repo(
    organization_id: uuid.UUID | str,
    *,
    created_by_id: int | None = None,
) -> ContextLayerConfig:
    """Create the organization's wiki with the default structure. Idempotent:
    an existing config is returned untouched."""
    existing = ContextLayerConfig.objects.filter(organization_id=organization_id).first()
    if existing is not None:
        return existing

    with repo_writer_lock(organization_id), tempfile.TemporaryDirectory(prefix="context-layer-") as tmp:
        workdir = Path(tmp) / "repo"
        workdir.mkdir()
        _run_git(["init", "--quiet", "--initial-branch", DEFAULT_BRANCH, str(workdir)], cwd=Path(tmp))
        write_default_structure(workdir)
        _lint_or_raise(workdir)
        head_sha = _commit_all(workdir, "Scaffold the context wiki", SYSTEM_AUTHOR)
        _upload_bundle(organization_id, head_sha, workdir)
        config, created = ContextLayerConfig.objects.get_or_create(
            organization_id=organization_id,
            defaults={"head_sha": head_sha, "created_by_id": created_by_id},
        )
        if not created:
            logger.info("context_layer.initialize_repo.lost_create_race", organization_id=str(organization_id))
        return config


def apply_changes(
    organization_id: uuid.UUID | str,
    *,
    message: str,
    mutate: Callable[[Path], None],
    author: CommitAuthor | None = None,
) -> str:
    """Run the writer protocol for a working-tree mutation and return the new head sha.

    `mutate` receives the checkout path and edits files in place; the store
    commits, lints, uploads, and lands the result. A no-op mutation returns the
    current head without landing anything.
    """
    author = author or SYSTEM_AUTHOR
    # All writers hold the per-org lock, so the CAS only loses when a previous
    # writer's lock expired mid-land and its CAS raced ours. One retry re-reads
    # the moved head and replays the mutation on top of it.
    for attempt in (1, 2):
        with repo_writer_lock(organization_id):
            expected_head = get_config(organization_id).head_sha
            with tempfile.TemporaryDirectory(prefix="context-layer-") as tmp:
                tmpdir = Path(tmp)
                bundle_path = _download_bundle(organization_id, expected_head, tmpdir)
                workdir = tmpdir / "repo"
                _clone_from_bundle(bundle_path, workdir)

                mutate(workdir)
                if not _has_changes(workdir):
                    return expected_head
                _lint_or_raise(workdir)
                new_head = _commit_all(workdir, message, author)
                _upload_bundle(organization_id, new_head, workdir)

                updated = ContextLayerConfig.objects.filter(
                    organization_id=organization_id, head_sha=expected_head
                ).update(head_sha=new_head)
                if updated:
                    return new_head
        logger.warning(
            "context_layer.apply_changes.head_moved",
            organization_id=str(organization_id),
            expected_head=expected_head,
            attempt=attempt,
        )
    raise HeadMovedError(f"head moved twice while landing changes for organization {organization_id}")


def purge_repo_history(organization_id: uuid.UUID | str, *, message: str = "Purge wiki history") -> str:
    """Rewrite the wiki to a single commit holding the current tree and delete
    every old bundle, so no dropped history survives in object storage. The
    escape hatch for sensitive content committed by mistake.

    Raises `PurgeIncompleteError` if the rewrite lands but an old bundle cannot
    be removed, so a caller never treats a partial purge as done.
    """

    def reinitialize_history(root: Path) -> None:
        shutil.rmtree(root / ".git")
        _run_git(["init", "--quiet", "--initial-branch", DEFAULT_BRANCH, str(root)], cwd=root)

    apply_changes(organization_id, message=message, mutate=reinitialize_history)
    # Re-take the lock and prune against the head as it stands now: another writer
    # may have landed on top of the rewritten tree, and only the current head's
    # bundle must survive.
    with repo_writer_lock(organization_id):
        head_sha = get_config(organization_id).head_sha
        _prune_bundles_except(organization_id, head_sha)
        return head_sha


def get_bundle_presigned_url(organization_id: uuid.UUID | str, *, expiration_seconds: int = 300) -> str:
    """Short-lived download URL for the current bundle, for sandbox mounts and export."""
    config = get_config(organization_id)
    url = object_storage.get_presigned_url(bundle_key(organization_id, config.head_sha), expiration=expiration_seconds)
    if url is None:
        raise ContextLayerStoreError(f"could not presign the bundle for organization {organization_id}")
    return url
