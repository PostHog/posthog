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


def list_bundle(prefix: str) -> list[str]:
    """Return the object keys present under ``prefix`` (empty list if none)."""
    return object_storage.list_objects(prefix) or []


def delete_bundle(prefix: str) -> None:
    """Delete every object under ``prefix``."""
    for key in list_bundle(prefix):
        object_storage.delete(key)
    logger.info("autoresearch_bundle_deleted", prefix=prefix)
