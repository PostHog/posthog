"""Every out-of-band detection line must survive the `posthog` logger clamp.

The posthoganalytics SDK claims the `posthog` logger name and clamps it to WARNING when it
builds its client, so every logger under `posthog.` inherits that level. The guards log a match
at INFO, which that clamp swallows: the refusal next to it still prints, so the gap is invisible
until someone checks production and finds the matches missing.

A guard under `products.` sits outside the clamp and needs no entry.
"""

import logging
from pathlib import Path

from django.conf import settings

REPO_ROOT = Path(__file__).parents[3]
DETECTION_EVENT = "security.oob_domain_seen"
SCANNED_ROOTS = ("posthog", "products", "ee", "common")
CLAMPED_PREFIX = "posthog."
SKIPPED_PARTS = ("node_modules", "__pycache__", "migrations")
VISIBLE_LEVELS = {logging.getLevelName(level) for level in (logging.DEBUG, logging.INFO)}


def _is_test(path: Path) -> bool:
    return path.name.startswith("test_") or path.name.endswith("_test.py") or "tests" in path.parts


def clamped_emitters() -> list[str]:
    """Logger names under `posthog.` that emit the detection event.

    Each guard calls `structlog.get_logger(__name__)`, so the module path is the logger name.
    """
    found: set[str] = set()
    for root in SCANNED_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            if any(part in SKIPPED_PARTS for part in path.parts) or _is_test(path):
                continue
            if DETECTION_EVENT not in path.read_text(errors="ignore"):
                continue
            name = ".".join(path.relative_to(REPO_ROOT).with_suffix("").parts)
            if name.startswith(CLAMPED_PREFIX):
                found.add(name)
    return sorted(found)


def test_every_clamped_detection_logger_can_emit_info() -> None:
    configured = settings.LOGGING["loggers"]
    missing = [name for name in clamped_emitters() if configured.get(name, {}).get("level") not in VISIBLE_LEVELS]
    assert not missing, (
        "These loggers emit "
        f"{DETECTION_EVENT} at INFO but sit under the clamped `posthog` logger, so the line never "
        "reaches production:\n"
        + "\n".join(f"  {name}" for name in missing)
        + "\n\nGive each one an explicit entry in posthog/settings/logs.py, next to the others that "
        'work around the same clamp:\n    "<logger>": {"level": "INFO", "handlers": ["console"], '
        '"propagate": False},'
    )
