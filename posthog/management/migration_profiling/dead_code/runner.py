"""Top-level orchestrator: parse → timeline → detectors → findings."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from posthog.management.migration_profiling.dead_code.detector_base import AnalysisContext, Detector
from posthog.management.migration_profiling.dead_code.detectors.add_remove_field import AddRemoveFieldDetector
from posthog.management.migration_profiling.dead_code.detectors.empty_runpython import EmptyRunPythonDetector
from posthog.management.migration_profiling.dead_code.models import Finding
from posthog.management.migration_profiling.dead_code.parser import (
    ParsedMigration,
    find_migration_files,
    parse_migration_file,
)
from posthog.management.migration_profiling.dead_code.timeline import build_timeline

logger = logging.getLogger(__name__)

# Default detector set — add new detectors here.
DEFAULT_DETECTORS: list[type[Detector]] = [
    AddRemoveFieldDetector,
    EmptyRunPythonDetector,
]


def run_detectors(
    repo_root: Path,
    profile_ops: list[dict[str, Any]] | None = None,
    detector_classes: list[type[Detector]] | None = None,
) -> list[Finding]:
    """Discover migration files under ``repo_root``, build context, run all
    registered detectors, and return aggregated findings."""
    detector_classes = detector_classes or DEFAULT_DETECTORS

    parsed_migrations: list[ParsedMigration] = []
    for path in find_migration_files(repo_root):
        parsed = parse_migration_file(path)
        if parsed is not None:
            parsed_migrations.append(parsed)

    timeline = build_timeline(parsed_migrations)
    by_app_name = {(m.app, m.name): m for m in parsed_migrations}

    ctx = AnalysisContext(
        timeline=timeline,
        migrations=parsed_migrations,
        migrations_by_app_name=by_app_name,
        profile_ops=profile_ops or [],
    )

    findings: list[Finding] = []
    for detector_cls in detector_classes:
        detector = detector_cls()
        try:
            findings.extend(detector.run(ctx))
        except Exception as exc:  # detectors shouldn't crash the report
            logger.warning("Detector %s raised %s; skipping its findings", detector.name, exc)

    findings.sort(key=lambda f: (-f.confidence, f.detector_name, f.summary))
    return findings
