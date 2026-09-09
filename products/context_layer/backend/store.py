"""Git bundle store for organization context wikis.

One bare Git repo per organization, serialized as a `git bundle` in object
storage, with the current head sha in Postgres (`ContextLayerConfig.head_sha`)
as a compare-and-swap pointer. Every writer follows the same protocol: acquire
the per-org Redis lock, download the bundle, clone to tmp, apply commits, lint,
upload the new bundle, CAS the head, release. Readers never take the lock.
"""

from __future__ import annotations

import re
import uuid
import shutil
import tempfile
import threading
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from django.utils import timezone

import structlog
from redis.exceptions import RedisError

from posthog.dataclasses import frozen
from posthog.ph_client import ph_scoped_capture
from posthog.redis import get_client
from posthog.storage import object_storage

from products.context_layer.backend import repo_lint
from products.context_layer.backend.models import ContextLayerConfig
from products.context_layer.backend.repo_lint import lint_repo
from products.context_layer.backend.scaffold import generate_index, generate_project_indexes, write_default_structure

logger = structlog.get_logger(__name__)

BUNDLE_KEY_PREFIX = "context_layer"
DEFAULT_BRANCH = "main"
BUNDLE_MAX_COMMITS = 100
BUNDLE_MAX_UNPACKED_BYTES = 200_000_000
# Sits far above what a legitimate 100-commit history over a 2,000-file wiki
# produces, and stops a flood of tiny objects from being sized at all.
BUNDLE_MAX_OBJECTS = 500_000
# Every incoming commit's tree is materialized and linted, so the cost is the
# sum across commits rather than the size of any one of them. A prose wiki lands
# far below this; a bundle that exceeds it has to be split.
BUNDLE_MAX_CUMULATIVE_TREE_BYTES = 1_000_000_000
DREAM_BRANCH_RE = re.compile(r"dream/\d{4}-\d{2}-\d{2}")
LOCK_TTL_MS = 60_000
LOCK_RENEW_INTERVAL_SECONDS = 20.0
GIT_TIMEOUT_SECONDS = 60
COMMITTER_NAME = "PostHog Context Layer"
COMMITTER_EMAIL = "context-layer@posthog.com"


class ContextLayerStoreError(Exception):
    pass


class DependencyUnavailableError(ContextLayerStoreError):
    """A binary the store shells out to (git) is missing from the host, so no
    read or write can run. Maps to HTTP 503 so the API fails cleanly instead of
    an unhandled 500."""


class RepoNotFoundError(ContextLayerStoreError):
    """The organization has no context layer repo (no config row or no bundle)."""


class RepoLockUnavailableError(ContextLayerStoreError):
    """Another writer holds the per-org lock; retry later."""


class HeadMovedError(ContextLayerStoreError):
    """The head sha moved underneath a landing writer, twice."""


class PurgeIncompleteError(ContextLayerStoreError):
    """A purge rewrote the history but could not remove every old bundle, so
    sensitive content may still be readable in object storage."""


class HeadConflictError(ContextLayerStoreError):
    """A write guarded by `required_head` was based on a stale head."""

    def __init__(self, *, current_head: str) -> None:
        super().__init__(f"the wiki head moved to {current_head}; re-read and retry")
        self.current_head = current_head


class BundleConflictError(ContextLayerStoreError):
    """A posted commit bundle could not be read or rebased onto the current head."""


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


@frozen
class BundleExport:
    """A presigned download URL for a bundle and the head sha it points at."""

    url: str
    head_sha: str


@frozen
class LandingStats:
    pages_added: int
    pages_modified: int
    pages_deleted: int
    total_files: int
    total_bytes: int


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


def _run_git(args: list[str], cwd: Path, stdin_text: str | None = None) -> str:
    try:
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
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as err:
        raise DependencyUnavailableError("git binary is not available") from err
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


def _prune_bundles_best_effort(organization_id: uuid.UUID | str, keep_heads: set[str]) -> None:
    """Delete bundles superseded by a landing, keeping the new and previous heads.

    The previous head stays so a reader that fetched the old pointer just before
    the CAS can still download it; the next landing removes it. Cleanup never
    fails the write — a missed prune only costs storage until the next landing.
    """
    keep_keys = {bundle_key(organization_id, head) for head in keep_heads}
    try:
        existing = object_storage.list_objects(bundle_prefix(organization_id)) or []
        stale = [key for key in existing if key not in keep_keys]
        if stale:
            object_storage.delete_objects(stale)
    except Exception:
        logger.exception("context_layer.prune_bundles_failed", organization_id=str(organization_id))


def _clone_from_bundle(bundle_path: Path, workdir: Path) -> None:
    _run_git(["clone", "--quiet", str(bundle_path), str(workdir)], cwd=bundle_path.parent)
    _run_git(["checkout", "--quiet", DEFAULT_BRANCH], cwd=workdir)


def _commit_all(workdir: Path, message: str, author: CommitAuthor) -> str:
    _run_git(["add", "--all"], cwd=workdir)
    _run_git(["commit", "--quiet", "--author", f"{author.name} <{author.email}>", "-m", message], cwd=workdir)
    return _run_git(["rev-parse", "HEAD"], cwd=workdir)


def _has_changes(workdir: Path) -> bool:
    return bool(_run_git(["status", "--porcelain"], cwd=workdir))


def _refresh_canonical_scripts(workdir: Path) -> bool:
    """Rewrite scripts/ to the content PostHog currently ships.

    Landing is the upgrade point: a wiki scaffolded under an older script
    version (or carrying a tampered copy) gets the canonical scripts restored
    as part of the landing commit instead of failing the pinned lint forever.
    """
    scripts_dir = workdir / "scripts"
    if scripts_dir.is_symlink() or not scripts_dir.is_dir():
        return False
    changed = False
    for name, content in repo_lint._canonical_scripts().items():
        target = scripts_dir / name
        if target.is_symlink():
            # Never write through a link: a checkout could point scripts/lint at
            # a path writable by the service, and write_text follows symlinks.
            target.unlink()
        if not target.exists() or target.read_text(encoding="utf-8", errors="replace") != content:
            target.write_text(content, encoding="utf-8")
            target.chmod(0o755)
            changed = True
    return changed


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
    with tempfile.TemporaryDirectory(prefix="context-layer-", ignore_cleanup_errors=True) as tmp:
        tmpdir = Path(tmp)
        bundle_path = _download_bundle(organization_id, config.head_sha, tmpdir)
        workdir = tmpdir / "repo"
        _clone_from_bundle(bundle_path, workdir)
        yield RepoCheckout(path=workdir, head_sha=config.head_sha)


def get_path_updated_at(checkout: RepoCheckout, path: str) -> datetime:
    return datetime.fromisoformat(_run_git(["log", "-1", "--format=%cI", "--", path], checkout.path))


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

    with (
        repo_writer_lock(organization_id),
        tempfile.TemporaryDirectory(prefix="context-layer-", ignore_cleanup_errors=True) as tmp,
    ):
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


def _run_landing(
    organization_id: uuid.UUID | str,
    *,
    prepare: Callable[[Path], str | None],
    required_head: str | None = None,
    lane: str = "interactive",
) -> str:
    """The landing half of the writer protocol, shared by every writer.

    `prepare` receives a working clone of the current head and returns the new
    head sha it committed, or `None` for a no-op. All writers hold the per-org
    lock, so the CAS only loses when a previous writer's lock expired mid-land
    and its CAS raced ours. One retry re-reads the moved head and replays
    `prepare` on top of it.
    """
    for attempt in (1, 2):
        with repo_writer_lock(organization_id):
            expected_head = get_config(organization_id).head_sha
            if required_head is not None and required_head != expected_head:
                raise HeadConflictError(current_head=expected_head)
            with tempfile.TemporaryDirectory(prefix="context-layer-", ignore_cleanup_errors=True) as tmp:
                tmpdir = Path(tmp)
                bundle_path = _download_bundle(organization_id, expected_head, tmpdir)
                workdir = tmpdir / "repo"
                _clone_from_bundle(bundle_path, workdir)

                new_head = prepare(workdir)
                if new_head is None:
                    return expected_head
                if _refresh_canonical_scripts(workdir):
                    new_head = _commit_all(workdir, "Update wiki scripts to the current version", SYSTEM_AUTHOR)
                index_path = workdir / "index.md"
                if index_path.is_symlink():
                    # Never write the generated index through a bundle-supplied
                    # symlink; lint would reject it later, but the write happens first.
                    index_path.unlink()
                generated_index = generate_index(workdir)
                if not index_path.exists() or index_path.read_text(encoding="utf-8") != generated_index:
                    index_path.write_text(generated_index, encoding="utf-8")
                    new_head = _commit_all(workdir, "Refresh the generated wiki index", SYSTEM_AUTHOR)
                generated_project_indexes = generate_project_indexes(workdir)
                project_indexes_changed = False
                for relative, content in generated_project_indexes.items():
                    generated_path = workdir / relative
                    if generated_path.is_symlink():
                        generated_path.unlink()
                    generated_path.parent.mkdir(parents=True, exist_ok=True)
                    if not generated_path.exists() or generated_path.read_text(encoding="utf-8") != content:
                        generated_path.write_text(content, encoding="utf-8")
                        project_indexes_changed = True
                if project_indexes_changed:
                    new_head = _commit_all(workdir, "Refresh generated project indexes", SYSTEM_AUTHOR)
                _lint_or_raise(workdir)
                stats = _landing_stats(workdir, expected_head, new_head)
                _upload_bundle(organization_id, new_head, workdir)

                updated = ContextLayerConfig.objects.filter(
                    organization_id=organization_id, head_sha=expected_head
                ).update(head_sha=new_head)
                if updated:
                    _prune_bundles_best_effort(organization_id, {new_head, expected_head})
                    with ph_scoped_capture() as capture:
                        capture(
                            distinct_id=str(organization_id),
                            event="context layer commits landed",
                            properties={
                                "organization_id": str(organization_id),
                                "lane": lane,
                                "pages_added": stats.pages_added,
                                "pages_modified": stats.pages_modified,
                                "pages_deleted": stats.pages_deleted,
                                "total_files": stats.total_files,
                                "total_bytes": stats.total_bytes,
                            },
                        )
                    return new_head
        logger.warning(
            "context_layer.landing.head_moved",
            organization_id=str(organization_id),
            expected_head=expected_head,
            attempt=attempt,
        )
    raise HeadMovedError(f"head moved twice while landing changes for organization {organization_id}")


EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _landing_stats(workdir: Path, old_head: str, new_head: str) -> LandingStats:
    counts = {"A": 0, "M": 0, "D": 0}
    try:
        _run_git(["cat-file", "-e", f"{old_head}^{{commit}}"], cwd=workdir)
    except ContextLayerStoreError:
        # A purge rewrites history, so the previous head is no longer an object
        # in the rewritten repo; count every page as added instead of failing.
        old_head = EMPTY_TREE_SHA
    for line in _run_git(["diff", "--name-status", old_head, new_head, "--", "*.md"], cwd=workdir).splitlines():
        status = line.split("\t", 1)[0][0]
        if status in counts:
            counts[status] += 1
    files = [
        path for path in workdir.rglob("*") if ".git" not in path.parts and path.is_file() and not path.is_symlink()
    ]
    return LandingStats(
        pages_added=counts["A"],
        pages_modified=counts["M"],
        pages_deleted=counts["D"],
        total_files=len(files),
        total_bytes=sum(path.stat().st_size for path in files),
    )


def apply_changes(
    organization_id: uuid.UUID | str,
    *,
    message: str,
    mutate: Callable[[Path], None],
    author: CommitAuthor | None = None,
    required_head: str | None = None,
) -> str:
    """Run the writer protocol for a working-tree mutation and return the new head sha.

    `mutate` receives the checkout path and edits files in place; the store
    commits, lints, uploads, and lands the result. A no-op mutation returns the
    current head without landing anything. `required_head` is the optimistic
    concurrency guard: when the head no longer matches, `HeadConflictError`
    carries the current head for the caller's 409.
    """

    def prepare(workdir: Path) -> str | None:
        mutate(workdir)
        if not _has_changes(workdir):
            return None
        return _commit_all(workdir, message, author or SYSTEM_AUTHOR)

    return _run_landing(organization_id, prepare=prepare, required_head=required_head)


def _assert_bundle_within_bounds(workdir: Path, fetched: str) -> None:
    """Reject bundles whose incoming history is out of proportion for a wiki.

    The upload cap only bounds the compressed pack, so the limits here are
    measured on the incoming range's logical shape: commit count, merge shape,
    the sum of uncompressed object sizes (what a compression bomb hides), and
    what each commit actually materializes on disk. All limits sit far above
    anything a legitimate write-back produces.
    """
    incoming_range = f"{DEFAULT_BRANCH}..{fetched}"
    incoming_commits = int(_run_git(["rev-list", "--count", incoming_range], cwd=workdir))
    if incoming_commits > BUNDLE_MAX_COMMITS:
        raise BundleConflictError(
            f"the posted bundle carries {incoming_commits} commits; at most {BUNDLE_MAX_COMMITS} can land at once"
        )
    merge_commits = int(_run_git(["rev-list", "--merges", "--count", incoming_range], cwd=workdir))
    if merge_commits:
        # The landing rebase linearizes history and silently drops content that
        # exists only in merge commits (a conflict resolution, for example), so
        # a bundle carrying merges must be linearized by its author instead.
        raise BundleConflictError(
            "the posted bundle contains merge commits; rebase your clone onto its origin/main and repost"
        )
    _assert_object_sizes_within_bounds(workdir, incoming_range)
    _assert_trees_within_bounds(workdir, incoming_range)


def _assert_object_sizes_within_bounds(workdir: Path, incoming_range: str) -> None:
    """Bound the unique objects the incoming range adds.

    Sizes come from one `cat-file --batch-check` process fed every object id, so
    a bundle carrying tens of thousands of tiny objects costs one git process
    rather than one per object.
    """
    object_ids = [
        line.split(maxsplit=1)[0]
        for line in _run_git(["rev-list", "--objects", incoming_range], cwd=workdir).splitlines()
        if line
    ]
    if len(object_ids) > BUNDLE_MAX_OBJECTS:
        raise BundleConflictError(
            f"the posted bundle carries {len(object_ids)} objects; at most {BUNDLE_MAX_OBJECTS} can land at once"
        )
    if not object_ids:
        return
    sizes = _run_git(["cat-file", "--batch-check"], cwd=workdir, stdin_text="\n".join(object_ids) + "\n")
    incoming_bytes = 0
    for line in sizes.splitlines():
        fields = line.split()
        # `<sha> missing` for anything unreadable; the fetch already proved the
        # range is complete, so treat it as a malformed bundle rather than zero.
        if len(fields) < 3:
            raise BundleConflictError(f"could not size an object in the posted bundle: {line}")
        incoming_bytes += int(fields[2])
        if incoming_bytes > BUNDLE_MAX_UNPACKED_BYTES:
            raise BundleConflictError(
                f"the posted bundle unpacks past the {BUNDLE_MAX_UNPACKED_BYTES // 1_000_000} MB limit"
            )


def _assert_trees_within_bounds(workdir: Path, incoming_range: str) -> None:
    """Bound what the incoming commits materialize, per commit and in total.

    The object-size sum counts a blob once, but a checkout pays for every path
    that references it, so a small bundle can still materialize gigabytes. Each
    commit's tree is measured by path before anything is checked out, and the
    running total bounds the whole lint pass.
    """
    cumulative_bytes = 0
    for sha in _run_git(["rev-list", "--reverse", incoming_range], cwd=workdir).split():
        footprint = _tree_materialized_size(workdir, sha)
        if footprint.file_count > repo_lint.MAX_FILE_COUNT:
            raise BundleConflictError(
                f"commit {sha[:12]} carries {footprint.file_count} files; the wiki allows {repo_lint.MAX_FILE_COUNT}"
            )
        if footprint.total_bytes > repo_lint.MAX_TOTAL_BYTES:
            raise BundleConflictError(
                f"commit {sha[:12]} checks out to more than the "
                f"{repo_lint.MAX_TOTAL_BYTES // 1_000_000} MB the wiki allows"
            )
        cumulative_bytes += footprint.total_bytes
        if cumulative_bytes > BUNDLE_MAX_CUMULATIVE_TREE_BYTES:
            raise BundleConflictError(
                f"the posted bundle's commits check out to more than the "
                f"{BUNDLE_MAX_CUMULATIVE_TREE_BYTES // 1_000_000} MB that can be linted at once; "
                "post it as several smaller bundles"
            )


@frozen
class _TreeFootprint:
    """What a commit's tree writes to disk, counted per path."""

    total_bytes: int
    file_count: int


def _tree_materialized_size(workdir: Path, sha: str) -> _TreeFootprint:
    listing = _run_git(["ls-tree", "-r", "--long", "--full-tree", sha], cwd=workdir)
    total_bytes = 0
    file_count = 0
    for line in listing.splitlines():
        metadata, _, _ = line.partition("\t")
        fields = metadata.split()
        if len(fields) < 4:
            continue
        file_count += 1
        # Submodule entries (`commit`) report `-` and materialize nothing.
        if fields[3].isdigit():
            total_bytes += int(fields[3])
    return _TreeFootprint(total_bytes=total_bytes, file_count=file_count)


def _lint_incoming_commits(workdir: Path, base: str, tip: str) -> None:
    """Lint every incoming commit's tree, not just the final one.

    Landed history is exportable and clonable, so a hazardous intermediate
    commit (a secret, an oversized dump) must fail the land even when a later
    commit removes it. `_assert_trees_within_bounds` has already bounded the
    total work this loop can do.
    """
    shas = _run_git(["rev-list", "--reverse", f"{base}..{tip}"], cwd=workdir).split()
    for sha in shas:
        _run_git(["checkout", "--quiet", "--force", sha], cwd=workdir)
        # Historical trees may carry earlier script versions (nothing executes
        # them); the landed tree is pinned separately by the final lint.
        errors = lint_repo(workdir, pin_scripts=False)
        if errors:
            _run_git(["checkout", "--quiet", "--force", tip], cwd=workdir)
            raise LintFailedError([f"commit {sha[:12]}: {error}" for error in errors])
    _run_git(["checkout", "--quiet", "--force", tip], cwd=workdir)


def _assert_dream_paths(workdir: Path, base: str, tip: str) -> None:
    changed: set[tuple[str, str]] = set()
    for sha in _run_git(["rev-list", "--reverse", f"{base}..{tip}"], cwd=workdir).split():
        for line in _run_git(
            ["diff-tree", "--no-commit-id", "--name-status", "--no-renames", "-r", sha], cwd=workdir
        ).splitlines():
            status, _, path = line.partition("\t")
            changed.add((status, path))
    forbidden = sorted(path for status, path in changed if not _dream_may_edit(path, status=status))
    if forbidden:
        raise BundleConflictError(
            "dreaming may edit context pages only; server-owned or structural paths changed: " + ", ".join(forbidden)
        )


def _dream_may_edit(path: str, *, status: str = "M") -> bool:
    parts = Path(path).parts
    if not path.endswith(".md") or not parts or Path(path).name == "index.md":
        return False
    if parts[0] in {"org", "areas", "decisions"}:
        return True
    return status == "M" and (
        len(parts) >= 3
        and parts[0] == "projects"
        and (parts[2] == "overview.md" or (parts[2] == "spaces" and len(parts) == 4))
    )


def _fetch_incoming_bundle(workdir: Path, bundle_bytes: bytes, ref: str) -> str | None:
    """Fetch `ref` from a posted bundle into the working clone; returns its sha,
    or None when it already equals the current head."""
    incoming = workdir.parent / "incoming.bundle"
    incoming.write_bytes(bundle_bytes)
    try:
        _run_git(["bundle", "verify", "--quiet", str(incoming)], cwd=workdir)
        _run_git(["fetch", "--quiet", str(incoming), ref], cwd=workdir)
    except ContextLayerStoreError as error:
        raise BundleConflictError(f"could not read the posted bundle: {error}") from error
    fetched = _run_git(["rev-parse", "FETCH_HEAD"], cwd=workdir)
    if fetched == _run_git(["rev-parse", "HEAD"], cwd=workdir):
        return None
    return fetched


def land_commit_bundle(
    organization_id: uuid.UUID | str, bundle_bytes: bytes, *, summary: str | None = None, lane: str = "dream"
) -> str:
    """Land commits an agent made in its own clone, posted back as a bundle.

    The bundle must carry the wiki's `main` ref, with the commits based on some
    (possibly stale) head we already store. The incoming commits are rebased
    onto the current head; a rebase conflict raises `BundleConflictError` so the
    agent can re-pull and retry. Every incoming commit is linted, and bundles
    that unpack past sane bounds are rejected.
    """

    def prepare(workdir: Path) -> str | None:
        fetched = _fetch_incoming_bundle(workdir, bundle_bytes, DEFAULT_BRANCH)
        if fetched is None:
            return None
        _assert_bundle_within_bounds(workdir, fetched)
        _run_git(["checkout", "--quiet", "-B", "incoming", fetched], cwd=workdir)
        try:
            _run_git(["rebase", "--quiet", DEFAULT_BRANCH], cwd=workdir)
        except ContextLayerStoreError as error:
            raise BundleConflictError(f"the posted commits conflict with the current head: {error}") from error
        rebased = _run_git(["rev-parse", "HEAD"], cwd=workdir)
        if summary:
            subject = _run_git(["log", "-1", "--format=%s"], cwd=workdir)
            _run_git(["commit", "--amend", "--quiet", "-m", subject, "-m", summary], cwd=workdir)
            rebased = _run_git(["rev-parse", "HEAD"], cwd=workdir)
        _lint_incoming_commits(workdir, DEFAULT_BRANCH, rebased)
        _run_git(["checkout", "--quiet", DEFAULT_BRANCH], cwd=workdir)
        _run_git(["merge", "--ff-only", "--quiet", rebased], cwd=workdir)
        return _run_git(["rev-parse", "HEAD"], cwd=workdir)

    return _run_landing(organization_id, prepare=prepare, lane=lane)


def land_dream_branch(
    organization_id: uuid.UUID | str,
    bundle_bytes: bytes,
    *,
    branch: str,
    summary: str | None = None,
) -> str:
    """Land a night's `dream/<YYYY-MM-DD>` branch as one two-parent merge commit
    (`dream: <date>`), keeping the branch ref, so every night stays trackable
    (`git log --merges`) and revertible (`git revert -m 1`) as a unit."""
    if not DREAM_BRANCH_RE.fullmatch(branch):
        raise BundleConflictError(f"{branch!r} is not a dream branch; expected dream/<YYYY-MM-DD>")

    def prepare(workdir: Path) -> str | None:
        fetched = _fetch_incoming_bundle(workdir, bundle_bytes, branch)
        if fetched is None:
            return None
        _assert_bundle_within_bounds(workdir, fetched)
        _assert_dream_paths(workdir, DEFAULT_BRANCH, fetched)
        _lint_incoming_commits(workdir, DEFAULT_BRANCH, fetched)
        # The lint walk leaves HEAD detached at the branch tip; the merge below
        # must run from main or it silently no-ops and the landing keeps the
        # old tree.
        _run_git(["checkout", "--quiet", "--force", DEFAULT_BRANCH], cwd=workdir)
        _run_git(["branch", "--force", branch, fetched], cwd=workdir)
        try:
            merge_args = ["merge", "--no-ff", "--quiet", "-m", f"dream: {branch.removeprefix('dream/')}"]
            if summary:
                merge_args.extend(["-m", summary])
            _run_git([*merge_args, branch], cwd=workdir)
        except ContextLayerStoreError as error:
            raise BundleConflictError(f"the dream branch conflicts with the current head: {error}") from error
        return _run_git(["rev-parse", "HEAD"], cwd=workdir)

    return _run_landing(organization_id, prepare=prepare, lane="dream")


def purge_repo_history(organization_id: uuid.UUID | str, *, message: str = "Purge wiki history") -> str:
    """Rewrite the wiki to a single commit holding the current tree and delete
    every old bundle, so no dropped history survives in object storage. The
    escape hatch for sensitive content committed by mistake.

    Raises `PurgeIncompleteError` if the rewrite lands but an old bundle cannot
    be removed, so a caller never treats a partial purge as done. The object
    storage bucket must not have versioning enabled, because a versioned bucket
    retains deleted bundle bodies as prior versions.
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
        try:
            _prune_bundles_except(organization_id, head_sha)
        except Exception:
            # The rewrite landed but old bundles with the purged content are
            # still readable; stamp the config so the partial purge is durable
            # state a human can find, not just a raised-and-lost exception.
            ContextLayerConfig.objects.filter(organization_id=organization_id).update(
                purge_incomplete_at=timezone.now()
            )
            with ph_scoped_capture() as capture:
                capture(
                    distinct_id=str(organization_id),
                    event="context layer purge incomplete",
                    properties={"organization_id": str(organization_id)},
                )
            raise
        ContextLayerConfig.objects.filter(organization_id=organization_id).update(purge_incomplete_at=None)
        return head_sha


def get_bundle_export(organization_id: uuid.UUID | str, *, expiration_seconds: int = 300) -> BundleExport:
    """Short-lived download URL for the current bundle, for sandbox mounts and export.

    Reads the head once, so the returned url and head_sha always name the same
    revision even if a writer lands between calls."""
    config = get_config(organization_id)
    url = object_storage.get_presigned_url(bundle_key(organization_id, config.head_sha), expiration=expiration_seconds)
    if url is None:
        raise ContextLayerStoreError(f"could not presign the bundle for organization {organization_id}")
    return BundleExport(url=url, head_sha=config.head_sha)
