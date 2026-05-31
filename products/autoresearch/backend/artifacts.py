"""
Artifact bundle storage for autoresearch models.

Each model is backed by a runnable bundle of agent-authored files in object
storage: ``train.py``, ``predict.py``, ``features.sql``, ``recipe.yml``.
Inference downloads the bundle and runs it in a sandbox (see
``sandbox_inference.py``); the in-process recipe path is the legacy fallback.

This module is a thin, team-scoped wrapper over ``posthog.storage.object_storage``.
Keys are prefixed by team / pipeline / training-run so history is preserved
naturally and bundles never collide across tenants.
"""

from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

import structlog

from posthog.storage import object_storage

logger = structlog.get_logger(__name__)

# The four files that make up a runnable model bundle.
TRAIN_PY = "train.py"
PREDICT_PY = "predict.py"
FEATURES_SQL = "features.sql"
RECIPE_YML = "recipe.yml"
BUNDLE_FILES: tuple[str, ...] = (TRAIN_PY, PREDICT_PY, FEATURES_SQL, RECIPE_YML)

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


class InvalidArtifactPath(ValueError):
    """Raised when an upload/get path would escape the run prefix or is malformed."""


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


@dataclass
class ArtifactBundle:
    """The agent-authored files describing one model. Stored as UTF-8 text."""

    train_py: str
    predict_py: str
    features_sql: str
    recipe_yml: str

    def as_files(self) -> dict[str, str]:
        return {
            TRAIN_PY: self.train_py,
            PREDICT_PY: self.predict_py,
            FEATURES_SQL: self.features_sql,
            RECIPE_YML: self.recipe_yml,
        }

    @classmethod
    def from_files(cls, files: dict[str, bytes]) -> ArtifactBundle:
        missing = [name for name in BUNDLE_FILES if name not in files]
        if missing:
            raise BundleNotFound(f"Bundle is missing required files: {', '.join(missing)}")
        return cls(
            train_py=files[TRAIN_PY].decode("utf-8"),
            predict_py=files[PREDICT_PY].decode("utf-8"),
            features_sql=files[FEATURES_SQL].decode("utf-8"),
            recipe_yml=files[RECIPE_YML].decode("utf-8"),
        )

    @classmethod
    def from_dir(cls, directory: str | Path) -> ArtifactBundle:
        """Load a bundle from a local directory (the fixture seed + future laptop-upload path)."""
        base = Path(directory)
        files = {name: (base / name).read_bytes() for name in BUNDLE_FILES if (base / name).exists()}
        return cls.from_files(files)


class BundleNotFound(Exception):
    """Raised when a bundle prefix has no (or an incomplete) set of files."""


def bundle_prefix(*, team_id: int, pipeline_id: str, training_run_id: str) -> str:
    """Object-storage key prefix (no trailing slash) for one training run's bundle."""
    folder = settings.OBJECT_STORAGE_TASKS_FOLDER
    return f"{folder}/autoresearch/team_{team_id}/pipeline_{pipeline_id}/run_{training_run_id}"


def write_bundle(prefix: str, bundle: ArtifactBundle) -> None:
    """Write all four bundle files under ``prefix``."""
    for name, content in bundle.as_files().items():
        object_storage.write(f"{prefix}/{name}", content)
    logger.info("autoresearch_bundle_written", prefix=prefix, files=len(BUNDLE_FILES))


def read_bundle(prefix: str) -> ArtifactBundle:
    """Read all four bundle files from ``prefix``. Raises ``BundleNotFound`` if any is absent."""
    files: dict[str, bytes] = {}
    for name in BUNDLE_FILES:
        content = object_storage.read_bytes(f"{prefix}/{name}", missing_ok=True)
        if content is not None:
            files[name] = content
    return ArtifactBundle.from_files(files)


def write_model(prefix: str, content: bytes) -> None:
    """Persist the fitted champion model (``model.pkl``) under ``prefix``."""
    object_storage.write(f"{prefix}/{MODEL_PKL}", content)
    logger.info("autoresearch_model_written", prefix=prefix, size=len(content))


def read_model(prefix: str) -> bytes | None:
    """Read the fitted champion model under ``prefix``, or None if it has not been fit yet."""
    return object_storage.read_bytes(f"{prefix}/{MODEL_PKL}", missing_ok=True)


def list_bundle(prefix: str) -> list[str]:
    """Return the object keys present under ``prefix`` (empty list if none)."""
    return object_storage.list_objects(prefix) or []


def delete_bundle(prefix: str) -> None:
    """Delete every object under ``prefix``."""
    for key in list_bundle(prefix):
        object_storage.delete(key)
    logger.info("autoresearch_bundle_deleted", prefix=prefix)


# ── Per-file access (the MCP upload/get/list/delete surface) ─────────────────────


@dataclass
class StoredArtifact:
    path: str
    size_bytes: int
    sha256: str


def write_artifact(prefix: str, path: str, content: bytes) -> StoredArtifact:
    """Write one file under ``prefix`` at the validated relative ``path``."""
    rel = normalize_artifact_path(path)
    if len(content) > MAX_ARTIFACT_BYTES:
        raise InvalidArtifactPath(f"Artifact {rel!r} is {len(content)} bytes; the limit is {MAX_ARTIFACT_BYTES} bytes.")
    object_storage.write(f"{prefix}/{rel}", content)
    logger.info("autoresearch_artifact_written", prefix=prefix, path=rel, size=len(content))
    return StoredArtifact(path=rel, size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())


def read_artifact(prefix: str, path: str) -> bytes:
    """Read one file under ``prefix``. Raises ``BundleNotFound`` if absent."""
    rel = normalize_artifact_path(path)
    content = object_storage.read_bytes(f"{prefix}/{rel}", missing_ok=True)
    if content is None:
        raise BundleNotFound(f"Artifact {rel!r} not found under {prefix}.")
    return content


def delete_artifact(prefix: str, path: str) -> bool:
    """Delete one file under ``prefix``. Returns False if it was not present."""
    rel = normalize_artifact_path(path)
    if object_storage.read_bytes(f"{prefix}/{rel}", missing_ok=True) is None:
        return False
    object_storage.delete(f"{prefix}/{rel}")
    logger.info("autoresearch_artifact_deleted", prefix=prefix, path=rel)
    return True


def list_artifacts(prefix: str) -> list[str]:
    """Return the relative paths present under ``prefix`` (sorted, prefix stripped)."""
    keys = object_storage.list_objects(prefix) or []
    rels = [key[len(prefix) + 1 :] for key in keys if key.startswith(f"{prefix}/")]
    return sorted(rels)
