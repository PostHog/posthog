"""Enable, disable, or inspect HTTP sample capture for warehouse-source syncs.

Sample capture writes anonymized request/response pairs to S3 for use as test
fixtures. It's controlled by a single Redis key (`data_imports:http_sample_capture`)
with a TTL — when the key expires, capture stops automatically.

Usage:

    # Enable capture for all 4xx Stripe responses, capped at 50 samples, for 30 minutes
    python manage.py warehouse_sources_capture_http_samples enable \
        --source-type stripe --response-code 4xx --limit 50 --ttl 30m

    # Multiple rules: pass --rule N times. Rules are evaluated in order and
    # the FIRST matching rule wins, so put the most specific rule first.
    python manage.py warehouse_sources_capture_http_samples enable \
        --rule source_type=stripe,response_code=429,limit=20 \
        --rule source_type=hubspot,response_code=*,team_id=12,limit=10 \
        --ttl 1h

    # Inspect the active config
    python manage.py warehouse_sources_capture_http_samples list

    # Disable early (clears the Redis key + counters)
    python manage.py warehouse_sources_capture_http_samples disable
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from posthog.redis import get_client
from posthog.temporal.data_imports.sources.common.http.sampling import (
    CAPTURE_CONFIG_REDIS_KEY,
    CAPTURE_COUNTER_KEY_PREFIX,
    MAX_CONFIG_TTL_SECONDS,
    WILDCARD,
    CaptureConfig,
    CaptureRule,
)

_TTL_RE = re.compile(r"^(\d+)([smhd])$")


def _parse_ttl(value: str) -> int:
    """Parse a duration like ``30m``, ``2h``, ``1d``, ``600s`` into seconds."""
    if not value:
        raise ValueError("ttl is required")
    match = _TTL_RE.match(value.strip().lower())
    if not match:
        # Plain integer falls back to seconds
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f"invalid ttl {value!r} — use e.g. 30m, 2h, 1d, or seconds") from exc
    n = int(match.group(1))
    unit = match.group(2)
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return n * multipliers[unit]


def _parse_rule_kv(spec: str, default_limit: int) -> CaptureRule:
    """Parse a `key=value,key=value` rule spec into a CaptureRule."""
    fields: dict[str, Any] = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"invalid rule fragment {part!r}, expected key=value")
        key, _, val = part.partition("=")
        fields[key.strip()] = val.strip()
    fields.setdefault("limit", default_limit)
    return CaptureRule.from_dict(fields)


class Command(BaseCommand):
    help = "Manage HTTP sample capture for warehouse-source syncs."

    def add_arguments(self, parser: CommandParser) -> None:
        sub = parser.add_subparsers(dest="action", required=True)

        enable = sub.add_parser("enable", help="Enable capture")
        enable.add_argument("--source-type", default=WILDCARD, help="Filter by source type (default: *)")
        enable.add_argument("--response-code", default=WILDCARD, help="HTTP code or class, e.g. 429 / 4xx (default: *)")
        enable.add_argument("--team-id", default=WILDCARD, help="Filter by team_id (default: *)")
        enable.add_argument("--schema-id", default=WILDCARD, help="Filter by schema id (default: *)")
        enable.add_argument("--limit", type=int, default=50, help="Max samples per rule (default: 50)")
        enable.add_argument(
            "--ttl",
            default="30m",
            help="How long capture stays enabled — e.g. 30m, 2h, 1d (default: 30m)",
        )
        enable.add_argument(
            "--rule",
            action="append",
            default=[],
            help="Add an extra rule as 'key=value,key=value'. Repeatable. Rules are evaluated in declared order; first match wins.",
        )

        sub.add_parser("disable", help="Disable capture (clears the Redis key + counters)")
        sub.add_parser("list", help="Print the active capture config, if any")

    def handle(self, *args: Any, **options: Any) -> None:
        action = options["action"]
        if action == "enable":
            self._enable(options)
        elif action == "disable":
            self._disable()
        elif action == "list":
            self._list()
        else:
            raise ValueError(f"Unknown action: {action}")

    def _emit(self, *lines: str) -> None:
        for line in lines:
            self.stdout.write(line)

    def _enable(self, options: dict[str, Any]) -> None:
        ttl_seconds = _parse_ttl(options["ttl"])
        if ttl_seconds <= 0:
            raise ValueError("ttl must be positive")
        if ttl_seconds > MAX_CONFIG_TTL_SECONDS:
            raise ValueError(f"ttl {ttl_seconds}s exceeds max {MAX_CONFIG_TTL_SECONDS}s (24h)")

        primary = CaptureRule(
            source_type=options["source_type"],
            response_code=options["response_code"],
            team_id=options["team_id"],
            schema_id=options["schema_id"],
            limit=options["limit"],
        )
        rules: list[CaptureRule] = [primary]
        for raw in options["rule"]:
            rules.append(_parse_rule_kv(raw, default_limit=options["limit"]))

        capture_id = uuid.uuid4().hex
        config = CaptureConfig(capture_id=capture_id, rules=tuple(rules))

        client = get_client()
        client.set(CAPTURE_CONFIG_REDIS_KEY, config.to_json(), ex=ttl_seconds)

        self._emit(f"Capture enabled — capture_id={capture_id}, ttl={ttl_seconds}s", "Rules:")
        for index, rule in enumerate(config.rules):
            self._emit(f"  [{index}] {rule}")
        self._emit(
            "",
            f"S3 prefix:  warehouse-sources-http-samples/{capture_id}/",
            "",
            "Capture stops automatically when the Redis key expires. Run with `disable` to stop early.",
        )

    def _disable(self) -> None:
        client = get_client()
        existing = client.get(CAPTURE_CONFIG_REDIS_KEY)
        if not existing:
            self._emit("Capture is already disabled (no config in Redis)")
            return

        config = CaptureConfig.from_json(existing)
        client.delete(CAPTURE_CONFIG_REDIS_KEY)
        if config is not None:
            # Best-effort cleanup of the per-rule and per-source counters.
            counter_pattern = f"{CAPTURE_COUNTER_KEY_PREFIX}:{config.capture_id}:*"
            try:
                cursor = 0
                deleted = 0
                while True:
                    cursor, keys = client.scan(cursor=cursor, match=counter_pattern, count=200)
                    if keys:
                        deleted += client.delete(*keys)
                    if cursor == 0:
                        break
                self._emit(f"Capture disabled — deleted {deleted} counter keys for capture_id={config.capture_id}")
            except Exception as exc:
                # Don't fail the command — the config key is already gone, capture has stopped.
                self._emit(f"Capture disabled — counter cleanup partial (Redis: {exc})")
        else:
            self._emit("Capture disabled — capture_id was unparseable, skipped counter cleanup")

    def _list(self) -> None:
        client = get_client()
        existing = client.get(CAPTURE_CONFIG_REDIS_KEY)
        if not existing:
            self._emit("Capture is not currently enabled")
            return
        config = CaptureConfig.from_json(existing)
        if config is None:
            self._emit("Capture key present but unparseable")
            return
        ttl = client.ttl(CAPTURE_CONFIG_REDIS_KEY)
        self._emit(
            f"capture_id: {config.capture_id}",
            f"ttl_seconds_remaining: {ttl}",
            f"S3 prefix: warehouse-sources-http-samples/{config.capture_id}/",
            f"rules ({len(config.rules)}):",
        )
        for index, rule in enumerate(config.rules):
            counter_key = f"{CAPTURE_COUNTER_KEY_PREFIX}:{config.capture_id}:{index}"
            try:
                used = int(client.get(counter_key) or 0)
            except Exception:
                used = -1
            self._emit(f"  [{index}] used={used}/{rule.limit}: {rule}")
