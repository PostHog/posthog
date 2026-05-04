"""Sample capture for tracked HTTP requests.

When the singleton Redis key `data_imports:http_sample_capture` is set,
matching outbound requests are anonymized and uploaded to object storage
under `warehouse-sources-http-samples/{capture_id}/{source_type}/{seq}.json`.

Operator workflow:

1. `python manage.py warehouse_sources_capture_http_samples ...` writes the
   config + TTL into Redis.
2. Active syncs see the config (refresh window ~30s) and start writing
   matching samples to S3.
3. After TTL expiry the config disappears; capture stops automatically.
4. Operator pulls the samples down and uses them as test fixtures.

Goals:

- Zero hot-path cost when capture is disabled (one Redis GET every 30s
  per worker, served from an in-process cache).
- Filtering on `(source_type, response_code, team_id, schema_id)` with
  `*` defaults.
- Per-rule capture limit enforced via Redis `INCR` so multiple workers
  share the same counter.
- All response keys preserved — values pass through `scrubadub`. Known
  auth headers are dropped wholesale; auth-bearing query params are
  scrubbed by `url_utils.scrub_url`.
"""

from __future__ import annotations

import json
import time
import uuid
import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlencode

from django.conf import settings

from posthog.redis import get_client
from posthog.storage import object_storage
from posthog.temporal.data_imports.sources.common.http.context import JobContext
from posthog.temporal.data_imports.sources.common.http.url_utils import _REDACT_PARAM_NAMES, scrub_url

if TYPE_CHECKING:
    from requests import PreparedRequest, Response

    from posthog.temporal.data_imports.sources.common.http.observer import RequestRecord

logger = logging.getLogger(__name__)

CAPTURE_CONFIG_REDIS_KEY = "data_imports:http_sample_capture"
CAPTURE_COUNTER_KEY_PREFIX = "data_imports:http_sample_capture:counter"
S3_PREFIX = "warehouse-sources-http-samples"
CONFIG_CACHE_TTL_SECONDS = 30
MAX_CONFIG_TTL_SECONDS = 24 * 60 * 60
WILDCARD = "*"

_REDACTED_HEADER = "REDACTED"
_REDACTED_FORM_VALUE = "REDACTED"
_REDACTED_SCRUB_FAILURE = "<scrub_failed>"
_AUTH_HEADER_NAMES: frozenset[str] = frozenset(
    {"authorization", "x-api-key", "x-auth-token", "cookie", "set-cookie", "proxy-authorization"}
)


@dataclass(frozen=True)
class CaptureRule:
    source_type: str = WILDCARD
    response_code: str = WILDCARD
    team_id: str = WILDCARD
    schema_id: str = WILDCARD
    limit: int = 0

    def matches(self, *, source_type: str, status_code: int | None, team_id: int, schema_id: str) -> bool:
        if self.source_type != WILDCARD and self.source_type != source_type:
            return False
        if self.team_id != WILDCARD and self.team_id != str(team_id):
            return False
        if self.schema_id != WILDCARD and self.schema_id != str(schema_id):
            return False
        return _matches_status(self.response_code, status_code)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CaptureRule:
        return cls(
            source_type=str(raw.get("source_type") or WILDCARD),
            response_code=str(raw.get("response_code") or WILDCARD),
            team_id=str(raw.get("team_id") or WILDCARD),
            schema_id=str(raw.get("schema_id") or WILDCARD),
            limit=int(raw.get("limit") or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "response_code": self.response_code,
            "team_id": self.team_id,
            "schema_id": self.schema_id,
            "limit": self.limit,
        }


@dataclass(frozen=True)
class CaptureConfig:
    capture_id: str
    rules: tuple[CaptureRule, ...] = field(default_factory=tuple)

    @classmethod
    def from_json(cls, raw: bytes | str) -> CaptureConfig | None:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            logger.warning("Failed to decode capture config JSON")
            return None

        capture_id = data.get("capture_id")
        if not capture_id:
            return None
        rules_raw = data.get("rules") or []
        rules = tuple(CaptureRule.from_dict(r) for r in rules_raw if isinstance(r, dict))
        return cls(capture_id=str(capture_id), rules=rules)

    def to_json(self) -> str:
        return json.dumps({"capture_id": self.capture_id, "rules": [r.to_dict() for r in self.rules]})


def _matches_status(rule_value: str, status_code: int | None) -> bool:
    if rule_value == WILDCARD:
        return True
    if status_code is None:
        return False
    if rule_value.endswith("xx") and len(rule_value) == 3 and rule_value[0].isdigit():
        return str(status_code).startswith(rule_value[0])
    return rule_value == str(status_code)


# In-process cache of the parsed Redis config. Thread-safe because the
# tracked transport is invoked from worker threads in the source iterator
# pool (see pipeline.py). The cache is intentionally per-process —
# refreshing every 30s in N workers is cheap.
_CONFIG_LOCK = threading.Lock()
_cached_config: CaptureConfig | None = None
_cached_config_fetched_at: float = 0.0


def _now() -> float:
    return time.monotonic()


def _load_config() -> CaptureConfig | None:
    global _cached_config, _cached_config_fetched_at

    with _CONFIG_LOCK:
        if _now() - _cached_config_fetched_at < CONFIG_CACHE_TTL_SECONDS:
            return _cached_config

        try:
            raw = get_client().get(CAPTURE_CONFIG_REDIS_KEY)
        except Exception:
            logger.debug("Capture-config Redis fetch failed", exc_info=True)
            # Keep the previously-cached value if any — beats hammering on errors.
            _cached_config_fetched_at = _now()
            return _cached_config

        _cached_config_fetched_at = _now()
        if raw is None:
            _cached_config = None
            return None

        config = CaptureConfig.from_json(raw)
        _cached_config = config
        return config


def _reset_cache_for_tests() -> None:
    """Test hook — clears the in-process cache."""
    global _cached_config, _cached_config_fetched_at
    with _CONFIG_LOCK:
        _cached_config = None
        _cached_config_fetched_at = 0.0


def _counter_key(capture_id: str, rule_index: int) -> str:
    return f"{CAPTURE_COUNTER_KEY_PREFIX}:{capture_id}:{rule_index}"


def _try_reserve_slot(capture_id: str, rule_index: int, limit: int) -> bool:
    """Atomically claim a sample slot. Returns True if the sample should be kept."""
    if limit <= 0:
        return False
    try:
        client = get_client()
        key = _counter_key(capture_id, rule_index)
        new_value = client.incr(key)
        try:
            ttl = client.ttl(CAPTURE_CONFIG_REDIS_KEY)
            client.expire(key, max(int(ttl) if isinstance(ttl, int) and ttl > 0 else MAX_CONFIG_TTL_SECONDS, 60))
        except Exception:
            logger.debug("Failed to set TTL on capture counter", exc_info=True)
        return int(new_value) <= limit
    except Exception:
        logger.debug("Failed to reserve sample slot", exc_info=True)
        return False


def _sample_object_key(capture_id: str, source_type: str, sequence: int) -> str:
    return f"{S3_PREFIX}/{capture_id}/{source_type}/{sequence:06d}.json"


def maybe_capture(
    *,
    request: PreparedRequest,
    response: Response | None,
    record: RequestRecord,
    ctx: JobContext,
) -> None:
    """Entry point used by the observer. No-op when no rule matches."""
    if response is None:
        return

    config = _load_config()
    if config is None:
        return

    matching = _first_match(
        config.rules,
        source_type=ctx.source_type,
        status_code=record.status_code,
        team_id=ctx.team_id,
        schema_id=ctx.external_data_schema_id,
    )
    if matching is None:
        return

    rule_index, rule = matching
    if not _try_reserve_slot(config.capture_id, rule_index, rule.limit):
        return

    payload = _build_sample_payload(request=request, response=response, record=record, ctx=ctx)
    sequence = _next_sequence(config.capture_id, ctx.source_type)
    key = _sample_object_key(config.capture_id, ctx.source_type, sequence)
    bucket = settings.OBJECT_STORAGE_BUCKET
    try:
        object_storage.write(key, payload, bucket=bucket)
    except Exception:
        logger.debug("Failed to write HTTP sample to object storage", exc_info=True)


def _first_match(
    rules: tuple[CaptureRule, ...],
    *,
    source_type: str,
    status_code: int | None,
    team_id: int,
    schema_id: str,
) -> tuple[int, CaptureRule] | None:
    for index, rule in enumerate(rules):
        if rule.matches(
            source_type=source_type,
            status_code=status_code,
            team_id=team_id,
            schema_id=schema_id,
        ):
            return index, rule
    return None


def _next_sequence(capture_id: str, source_type: str) -> int:
    """Per-source monotonic sequence — used only to give each S3 key a unique suffix."""
    try:
        client = get_client()
        return int(client.incr(f"{CAPTURE_COUNTER_KEY_PREFIX}:{capture_id}:seq:{source_type}"))
    except Exception:
        # Fall back to a random tail; we only need uniqueness, not ordering.
        return int(uuid.uuid4().int >> 96)


def _build_sample_payload(
    *,
    request: PreparedRequest,
    response: Response,
    record: RequestRecord,
    ctx: JobContext,
) -> str:
    request_headers = _scrub_headers(dict(request.headers or {}))
    response_headers = _scrub_headers(dict(response.headers or {}))
    request_body = _scrub_body(request.body)
    response_body = _scrub_body(_safe_response_text(response))

    sample = {
        "captured_at_unix_ms": int(time.time() * 1000),
        "context": ctx.as_log_fields(),
        "request": {
            "method": (request.method or "GET").upper(),
            "url": scrub_url(request.url or ""),
            "headers": request_headers,
            "body": request_body,
        },
        "response": {
            "status": response.status_code,
            "headers": response_headers,
            "body": response_body,
            "elapsed_ms": record.latency_ms,
        },
    }
    return json.dumps(sample, default=str)


def _safe_response_text(response: Response) -> str | None:
    try:
        return response.text
    except Exception:
        return None


def _scrub_headers(headers: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for name, value in headers.items():
        if name.lower() in _AUTH_HEADER_NAMES:
            cleaned[name] = _REDACTED_HEADER
            continue
        cleaned[name] = _scrub_string(str(value))
    return cleaned


def _scrub_body(body: Any) -> Any:
    if body is None:
        return None
    if isinstance(body, bytes | bytearray):
        try:
            body = body.decode("utf-8")
        except UnicodeDecodeError:
            return f"<binary {len(body)} bytes>"
    if isinstance(body, str):
        parsed = _try_json(body)
        if parsed is not None:
            return _scrub_value(parsed)
        # OAuth token-exchange / refresh / authorization-code flows post
        # `application/x-www-form-urlencoded` bodies like
        # `grant_type=refresh_token&client_id=...&client_secret=...&refresh_token=...`.
        # scrubadub treats those as opaque text and won't recognise OAuth
        # secrets, so we detect form-shaped bodies up front and redact by
        # key name against the same denylist used for URL query params.
        form = _try_form_urlencoded(body)
        if form is not None:
            return form
        return _scrub_string(body)
    return _scrub_value(body)


def _try_json(text: str) -> Any | None:
    text_stripped = text.lstrip()
    if not text_stripped or text_stripped[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return None


def _try_form_urlencoded(text: str) -> str | None:
    """Detect `application/x-www-form-urlencoded` bodies and scrub auth params.

    Returns the scrubbed body as a string, or `None` if the input doesn't
    look like a form-encoded payload (in which case the caller falls back
    to scrubadub on the raw text).
    """
    stripped = text.strip()
    if not stripped or "=" not in stripped or "\n" in stripped or " " in stripped.split("=", 1)[0]:
        return None
    try:
        pairs = parse_qsl(stripped, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    # Require at least one key=value pair to call this a form body.
    if not pairs:
        return None
    scrubbed = [
        (name, _REDACTED_FORM_VALUE if name.lower() in _REDACT_PARAM_NAMES else _scrub_string(value))
        for name, value in pairs
    ]
    return urlencode(scrubbed, doseq=False)


def _scrub_value(value: Any) -> Any:
    """Walk a JSON-shaped value, scrubbing string leaves but preserving keys."""
    if isinstance(value, dict):
        return {k: _scrub_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_value(item) for item in value]
    if isinstance(value, str):
        return _scrub_string(value)
    return value


# scrubadub's default Scrubber is constructed lazily; the import is heavy.
_scrubber_lock = threading.Lock()
_scrubber: Any | None = None


def _get_scrubber() -> Any:
    global _scrubber
    if _scrubber is not None:
        return _scrubber
    with _scrubber_lock:
        if _scrubber is None:
            import scrubadub

            _scrubber = scrubadub.Scrubber()
        return _scrubber


def _scrub_string(value: str) -> str:
    if not value:
        return value
    try:
        return _get_scrubber().clean(value)
    except Exception:
        # Fail closed: a scrubadub failure on a value we couldn't otherwise
        # categorise must not leak the raw, potentially sensitive content
        # into the captured sample. Replace with a placeholder so the
        # surrounding structure (header dict, body shape) is preserved
        # for fixture use, but the unredacted value never lands in S3.
        logger.debug("scrubadub failed; replacing value with placeholder", exc_info=True)
        return _REDACTED_SCRUB_FAILURE
