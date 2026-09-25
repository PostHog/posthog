import structlog
from pydantic import ValidationError

from posthog.exceptions_capture import capture_exception
from posthog.query_cache.metrics import count_query_cache_schema_drift

logger = structlog.get_logger(__name__)

# A rolling deploy runs two schema versions at once, so a pod can read an entry that a pod on
# the other image wrote. Each shape below means the entry names something this pod's schema
# does not know yet: a field added to a response model, or a value added to a Literal or an
# Enum. Any other shape is a genuinely malformed entry.
_SCHEMA_DRIFT_ERROR_TYPES = frozenset({"extra_forbidden", "literal_error", "enum"})


def is_schema_drift(error: ValidationError) -> bool:
    """Whether a cached response failed validation only because another schema version wrote it."""
    errors = error.errors()
    return bool(errors) and all(error_detail["type"] in _SCHEMA_DRIFT_ERROR_TYPES for error_detail in errors)


def report_cached_response_parse_failure(error: Exception, response_type: str) -> None:
    """Report an unparseable cache entry. The caller recomputes the query either way."""
    if isinstance(error, ValidationError) and is_schema_drift(error):
        # The message carries no model or field name, so a response-schema change does not
        # mint a new error tracking issue on every rollout.
        logger.info("query_cache_schema_drift", response_type=response_type)
        count_query_cache_schema_drift(response_type)
    else:
        capture_exception(Exception(f"Error parsing cached response: {error}"))
