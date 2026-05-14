import hashlib

import structlog
from asgiref.sync import async_to_sync
from celery import shared_task

from posthog.models.team.team import Team
from posthog.redis import get_client

logger = structlog.get_logger(__name__)

CSP_SIGNAL_SOURCE_PRODUCT = "csp_reporting"
CSP_SIGNAL_SOURCE_TYPE = "violation"
CSP_SIGNAL_WEIGHT = 0.5
CSP_SIGNAL_DEDUP_TTL_SECONDS = 60 * 60 * 24
CSP_SIGNAL_DEDUP_KEY_PREFIX = "csp_signal_dedup"


def _stringify(value: object) -> str:
    return "" if value is None else str(value)


def _csp_property(properties: dict, key: str) -> object:
    return properties.get(f"$csp_{key}")


def _fingerprint(properties: dict) -> str:
    fingerprint_input = "|".join(
        _stringify(_csp_property(properties, key))
        for key in ("violated_directive", "blocked_url", "document_url", "source_file")
    )
    return hashlib.sha1(fingerprint_input.encode("utf-8")).hexdigest()


def _dedup_key(team_id: int, fingerprint: str) -> str:
    return f"{CSP_SIGNAL_DEDUP_KEY_PREFIX}:{team_id}:{fingerprint}"


def _source_id(fingerprint: str) -> str:
    return f"csp:{fingerprint}"


def _build_description(properties: dict) -> str:
    violated_directive = _stringify(_csp_property(properties, "violated_directive")) or "unknown directive"
    blocked_url = _stringify(_csp_property(properties, "blocked_url")) or "unknown resource"
    document_url = _stringify(_csp_property(properties, "document_url")) or "unknown page"
    disposition = _stringify(_csp_property(properties, "disposition")) or "unknown"
    source_file = _stringify(_csp_property(properties, "source_file"))
    line_number = _stringify(_csp_property(properties, "line_number"))
    column_number = _stringify(_csp_property(properties, "column_number"))
    user_agent = _stringify(_csp_property(properties, "user_agent"))

    location = source_file
    if location and line_number:
        location = f"{source_file}:{line_number}"
        if column_number:
            location = f"{location}:{column_number}"

    lines = [
        f"CSP violation: directive '{violated_directive}' blocked '{blocked_url}' on '{document_url}'.",
        f"Disposition: {disposition}.",
    ]
    if location:
        lines.append(f"Source: {location}.")
    if user_agent:
        lines.append(f"Browser: {user_agent}.")
    lines.append(
        "This is a Content Security Policy report sent by a user's browser. Investigate whether "
        "the blocked resource is (1) legitimate and the CSP policy needs widening, (2) an injected "
        "or compromised script indicating a security incident, or (3) a third-party script the team "
        "should remove."
    )
    return "\n".join(lines)


def _build_extra(properties: dict) -> dict:
    def get_str(key: str) -> str | None:
        value = _csp_property(properties, key)
        return None if value is None else str(value)

    def get_number(key: str) -> float | None:
        value = _csp_property(properties, key)
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return {
        "document_url": get_str("document_url"),
        "violated_directive": get_str("violated_directive"),
        "effective_directive": get_str("effective_directive"),
        "blocked_url": get_str("blocked_url"),
        "source_file": get_str("source_file"),
        "line_number": get_number("line_number"),
        "column_number": get_number("column_number"),
        "disposition": get_str("disposition"),
        "user_agent": get_str("user_agent"),
    }


def enqueue_csp_violation_signal(team_id: int, properties: dict) -> bool:
    """
    Throttle on (team_id, violation fingerprint) for 24h and, on first sight, enqueue a Celery
    task that calls emit_signal. Returns True if a task was enqueued, False if throttled.

    Throttling uses Redis SET NX EX so it survives across web workers and never blocks the
    request path. Signal emission itself is best-effort: if it fails, the violation event has
    already been captured through the normal ingestion path.
    """
    fingerprint = _fingerprint(properties)
    key = _dedup_key(team_id, fingerprint)

    try:
        acquired = get_client().set(key, "1", nx=True, ex=CSP_SIGNAL_DEDUP_TTL_SECONDS)
    except Exception:
        logger.exception("csp_signal_throttle_check_failed", team_id=team_id, fingerprint=fingerprint)
        return False

    if not acquired:
        return False

    description = _build_description(properties)
    extra = _build_extra(properties)
    source_id = _source_id(fingerprint)

    emit_csp_violation_signal_task.delay(
        team_id=team_id,
        source_id=source_id,
        description=description,
        extra=extra,
    )
    return True


@shared_task(ignore_result=True, max_retries=0)
def emit_csp_violation_signal_task(team_id: int, source_id: str, description: str, extra: dict) -> None:
    from products.signals.backend.api import emit_signal

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        logger.warning("csp_signal_emit_missing_team", team_id=team_id, source_id=source_id)
        return

    try:
        async_to_sync(emit_signal)(
            team=team,
            source_product=CSP_SIGNAL_SOURCE_PRODUCT,
            source_type=CSP_SIGNAL_SOURCE_TYPE,
            source_id=source_id,
            description=description,
            weight=CSP_SIGNAL_WEIGHT,
            extra=extra,
        )
    except Exception:
        logger.exception(
            "csp_signal_emit_failed",
            team_id=team_id,
            source_id=source_id,
        )
