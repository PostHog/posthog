from typing import Any

from rest_framework.utils.encoders import JSONEncoder

# Lives in its own leaf module (only `rest_framework.utils.encoders`, no
# `rest_framework.renderers`) because `posthog.utils` imports this at module
# load, and `posthog.utils` is imported during Django settings evaluation.
# `rest_framework.renderers` reads `api_settings` in its class bodies, which
# would freeze DRF settings before `REST_FRAMEWORK` is fully configured — see
# the `django-startup-time` skill.
_drf_default = JSONEncoder().default


def orjson_default(obj: Any) -> Any:
    """Fallback serializer for ``orjson.dumps`` that tolerates non-UTF-8 bytes.

    orjson calls this for any value it can't natively encode, including ``bytes``.
    DRF's encoder decodes bytes as strict UTF-8, which raises on binary / non-UTF-8
    content (common in data-warehouse text columns). orjson turns a raising
    ``default`` into a generic ``TypeError: Type is not JSON serializable: bytes``,
    voiding the whole payload over a single bad cell. Decode leniently instead so
    one cell can't fail an entire query result or API response.
    """
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return _drf_default(obj)
