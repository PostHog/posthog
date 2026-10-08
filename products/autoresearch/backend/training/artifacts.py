"""
Artifact bundle storage for autoresearch models.

Each model is backed by a runnable bundle of agent-authored files in object
storage: ``train.py``, ``predict.py``, ``features.sql``.
Inference downloads the bundle and runs it in a sandbox (see
``sandbox_inference.py``); the in-process recipe path is the legacy fallback.

This module is a thin, team-scoped wrapper over ``posthog.storage.object_storage``.
Keys are prefixed by team / pipeline / training-run so history is preserved
naturally and bundles never collide across tenants.
"""

from __future__ import annotations

import re
import hashlib
from pathlib import Path

from django.conf import settings

import structlog

from posthog.dataclasses import frozen
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError

from products.autoresearch.backend.training.recipe_validation import RecipeValidationError, validate_feature_sql

logger = structlog.get_logger(__name__)

# The files that make up a runnable model bundle.
TRAIN_PY = "train.py"
PREDICT_PY = "predict.py"
FEATURES_SQL = "features.sql"
BUNDLE_FILES: tuple[str, ...] = (TRAIN_PY, PREDICT_PY, FEATURES_SQL)

# The fitted champion model, produced by the training run (train.py against the
# training population) and persisted alongside the bundle so predict runs are pure
# inference — they load this pickle and run predict.py only, never re-fitting.
MODEL_PKL = "model.pkl"

# Relative paths an agent may upload: bundle files at the top level plus optional
# eda/ notebooks. Conservative on purpose — segment names are limited to word
# chars, dot, and dash so nothing can climb out of the run prefix.
_SAFE_PATH_SEGMENT = re.compile(r"^[\w.\-]+$")
# A single file upload caps here so one base64 MCP payload can't blow memory.
MAX_ARTIFACT_BYTES = 10 * 1024 * 1024
# S3 rejects object keys longer than this many UTF-8 bytes.
MAX_OBJECT_KEY_BYTES = 1024


class InvalidArtifact(ValueError):
    """Raised when an agent-supplied artifact is refused before it reaches storage."""


class InvalidArtifactPath(InvalidArtifact):
    """Raised when an upload/get path would escape the run prefix or is malformed."""


class InvalidArtifactContent(InvalidArtifact):
    """Raised when an upload is too large, or a bundle file is empty, not UTF-8, or fails validation."""


def normalize_artifact_path(path: str) -> str:
    """
    Validate and normalize a relative artifact path. Rejects absolute paths,
    traversal (``..``), and segments with unexpected characters.
    """
    candidate = (path or "").strip().lstrip("/")
    if not candidate:
        raise InvalidArtifactPath("Artifact path must not be empty.")
    segments = candidate.split("/")
    for seg in segments:
        if seg in ("", ".", "..") or not _SAFE_PATH_SEGMENT.match(seg):
            raise InvalidArtifactPath(
                f"Invalid artifact path {path!r}: each segment must match [A-Za-z0-9_.-] and not be '.' or '..'."
            )
    return "/".join(segments)


def _artifact_key(prefix: str, rel: str) -> str:
    """The object key for the normalized relative path ``rel`` under ``prefix``, length-checked."""
    key = f"{prefix}/{rel}"
    if len(key.encode("utf-8")) > MAX_OBJECT_KEY_BYTES:
        raise InvalidArtifactPath(
            f"Artifact path {rel!r} is too long: the storage key is limited to {MAX_OBJECT_KEY_BYTES} bytes."
        )
    return key


def _require_storage() -> None:
    # The shared storage layer swaps in a client whose write() is a silent no-op when object
    # storage is disabled. Acknowledging an upload that was never stored makes the bundle
    # vanish on its next read, so refuse the write up front.
    if not settings.OBJECT_STORAGE_ENABLED:
        raise ObjectStorageError(
            "Object storage is disabled (OBJECT_STORAGE_ENABLED), so the artifact cannot be stored."
        )


def _bundle_text(name: str, content: bytes) -> str:
    """Decode one bundle file, refusing empty or non-UTF-8 content."""
    if not content.strip():
        raise InvalidArtifactContent(f"Bundle file {name!r} is empty.")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as e:
        raise InvalidArtifactContent(f"Bundle file {name!r} is not valid UTF-8 text.") from e


def _validate_bundle_file(name: str, content: bytes) -> None:
    """
    Check a bundle file at upload time, so a broken bundle is refused before it is acknowledged.

    ``features.sql`` gets the same static checks as a recorded recipe: fitting and inference run
    the uploaded query, not the recorded snapshot, so an upload that skipped validation could
    read the wall clock or drop the ``{anchors}`` cutoff and leak the outcome window.
    """
    text = _bundle_text(name, content)
    if name != FEATURES_SQL:
        return
    try:
        validate_feature_sql(text)
    except RecipeValidationError as e:
        raise InvalidArtifactContent(f"Bundle file {name!r} was rejected: {e}") from e


@frozen
class ArtifactBundle:
    """The agent-authored files describing one model. Stored as UTF-8 text."""

    train_py: str
    predict_py: str
    features_sql: str

    def as_files(self) -> dict[str, str]:
        return {
            TRAIN_PY: self.train_py,
            PREDICT_PY: self.predict_py,
            FEATURES_SQL: self.features_sql,
        }

    @classmethod
    def from_files(cls, files: dict[str, bytes]) -> ArtifactBundle:
        missing = [name for name in BUNDLE_FILES if name not in files]
        if missing and files:
            raise PartialBundle(f"Bundle is missing required files: {', '.join(missing)}")
        if missing:
            raise BundleNotFound(f"Bundle is missing required files: {', '.join(missing)}")
        return cls(
            train_py=_bundle_text(TRAIN_PY, files[TRAIN_PY]),
            predict_py=_bundle_text(PREDICT_PY, files[PREDICT_PY]),
            features_sql=_bundle_text(FEATURES_SQL, files[FEATURES_SQL]),
        )

    @classmethod
    def from_dir(cls, directory: str | Path) -> ArtifactBundle:
        """Load a bundle from a local directory (the fixture seed + future laptop-upload path)."""
        base = Path(directory)
        files = {name: (base / name).read_bytes() for name in BUNDLE_FILES if (base / name).exists()}
        return cls.from_files(files)


class BundleNotFound(Exception):
    """Raised when a bundle prefix has no (or an incomplete) set of files."""


class PartialBundle(BundleNotFound):
    """
    Raised when a prefix holds some bundle files but not all three.

    A caller that treats a missing bundle as "the agent did not upload one" must not treat
    this the same way. An interrupted upload would then take the legacy recipe path and
    serve an implementation the agent never wrote.
    """


def bundle_prefix(*, team_id: int, pipeline_id: str, training_run_id: str) -> str:
    """Object-storage key prefix (no trailing slash) for one training run's bundle."""
    folder = settings.OBJECT_STORAGE_TASKS_FOLDER
    return f"{folder}/autoresearch/team_{team_id}/pipeline_{pipeline_id}/run_{training_run_id}"


def write_bundle(prefix: str, bundle: ArtifactBundle) -> None:
    """Write all bundle files under ``prefix``, with the same checks as a per-file upload."""
    for name, content in bundle.as_files().items():
        write_artifact(prefix, name, content.encode("utf-8"))
    logger.info("autoresearch_bundle_written", prefix=prefix, files=len(BUNDLE_FILES))


def read_bundle(prefix: str) -> ArtifactBundle:
    """Read all bundle files from ``prefix``. Raises ``BundleNotFound`` if any is absent."""
    files: dict[str, bytes] = {}
    for name in BUNDLE_FILES:
        content = object_storage.read_bytes(f"{prefix}/{name}", missing_ok=True)
        if content is not None:
            files[name] = content
    return ArtifactBundle.from_files(files)


def write_model(prefix: str, content: bytes) -> None:
    """Persist the fitted champion model (``model.pkl``) under ``prefix``."""
    _require_storage()
    object_storage.write(f"{prefix}/{MODEL_PKL}", content)
    logger.info("autoresearch_model_written", prefix=prefix, size=len(content))


def read_model(prefix: str) -> bytes | None:
    """Read the fitted champion model under ``prefix``, or None if it has not been fit yet."""
    return object_storage.read_bytes(f"{prefix}/{MODEL_PKL}", missing_ok=True)


# ── Per-file access (the MCP upload/get/list/delete surface) ─────────────────────


@frozen
class StoredArtifact:
    path: str
    size_bytes: int
    sha256: str


def write_artifact(prefix: str, path: str, content: bytes) -> StoredArtifact:
    """Write one file under ``prefix`` at the validated relative ``path``."""
    rel = normalize_artifact_path(path)
    key = _artifact_key(prefix, rel)
    if len(content) > MAX_ARTIFACT_BYTES:
        raise InvalidArtifactContent(
            f"Artifact {rel!r} is {len(content)} bytes; the limit is {MAX_ARTIFACT_BYTES} bytes."
        )
    if rel in BUNDLE_FILES:
        _validate_bundle_file(rel, content)
    _require_storage()
    object_storage.write(key, content)
    logger.info("autoresearch_artifact_written", prefix=prefix, path=rel, size=len(content))
    return StoredArtifact(path=rel, size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())


def read_artifact(prefix: str, path: str) -> bytes:
    """Read one file under ``prefix``. Raises ``BundleNotFound`` if absent."""
    rel = normalize_artifact_path(path)
    key = _artifact_key(prefix, rel)
    content = object_storage.read_bytes(key, missing_ok=True)
    if content is None:
        raise BundleNotFound(f"Artifact {rel!r} not found under {prefix}.")
    return content


def delete_artifact(prefix: str, path: str) -> bool:
    """Delete one file under ``prefix``. Returns False if it was not present."""
    rel = normalize_artifact_path(path)
    key = _artifact_key(prefix, rel)
    if object_storage.read_bytes(key, missing_ok=True) is None:
        return False
    object_storage.delete(key)
    logger.info("autoresearch_artifact_deleted", prefix=prefix, path=rel)
    return True


def list_artifacts(prefix: str) -> list[str]:
    """Return the relative paths present under ``prefix`` (sorted, prefix stripped)."""
    keys = object_storage.list_objects(prefix) or []
    rels = [key[len(prefix) + 1 :] for key in keys if key.startswith(f"{prefix}/")]
    return sorted(rels)
