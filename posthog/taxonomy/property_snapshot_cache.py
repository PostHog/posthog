"""Redis storage for per-project property snapshots that a Celery task rebuilds in the background.

The 30-day query counts and the last-sent dates of properties are both slow to compute and change
slowly. A request serves the cached snapshot and queues at most one rebuild when it is stale.
"""

import json
import zlib
from datetime import timedelta
from typing import Any

from django.core.cache import cache

import structlog

from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)


@frozen
class PropertySnapshotCache:
    name: str
    format_version: int
    stale_after: timedelta
    # Past this age the snapshot is gone and the next request must build or queue it again.
    ttl: timedelta
    # Longer than a rebuild takes, so a crashed worker blocks rebuilds for at most this long.
    rebuild_marker_ttl: timedelta

    def _key(self, scope: str) -> str:
        return f"property_definition:{self.name}:v{self.format_version}:{scope}"

    def _rebuild_marker_key(self, scope: str) -> str:
        return f"property_definition:{self.name}_rebuild:{scope}"

    def read(self, scope: str) -> dict[str, Any] | None:
        raw = cache.get(self._key(scope))
        if raw is None:
            return None
        try:
            return json.loads(zlib.decompress(raw))
        except (ValueError, zlib.error):
            logger.warning("property_snapshot_unreadable", snapshot=self.name, scope=scope)
            return None

    def write(self, scope: str, payload: dict[str, Any]) -> None:
        # A project can have thousands of properties, so compress the snapshot before it goes to Redis.
        raw = zlib.compress(json.dumps(payload, separators=(",", ":")).encode())
        cache.set(self._key(scope), raw, timeout=int(self.ttl.total_seconds()))

    def claim_rebuild(self, scope: str) -> bool:
        # `add` sets the marker only when it is absent, so concurrent requests queue one rebuild.
        return cache.add(self._rebuild_marker_key(scope), True, timeout=int(self.rebuild_marker_ttl.total_seconds()))

    def release_rebuild(self, scope: str) -> None:
        cache.delete(self._rebuild_marker_key(scope))
