from typing import Any
from urllib.parse import urlparse

from posthog.cloud_utils import is_cloud
from posthog.temporal.data_imports.sources.common.mixins import is_http_host_safe

REQUIRED_TOP_LEVEL_KEYS = ("client", "resources")
ALLOWED_AUTH_TYPES = frozenset({"bearer", "api_key", "http_basic"})
ALLOWED_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})


class ManifestValidationError(ValueError):
    """Raised when the user-provided manifest doesn't conform to RESTAPIConfig."""


def validate_manifest(manifest: Any) -> None:
    """Validate the shape of a user-provided REST API manifest.

    Only checks structural correctness — the safety of any URLs in the
    manifest is checked separately by :func:`validate_manifest_urls`, which
    needs the team_id for cloud-vs-self-hosted handling.
    """
    if not isinstance(manifest, dict):
        raise ManifestValidationError("Manifest must be a JSON object")

    missing = [key for key in REQUIRED_TOP_LEVEL_KEYS if key not in manifest]
    if missing:
        raise ManifestValidationError(f"Manifest is missing required keys: {', '.join(missing)}")

    client = manifest["client"]
    if not isinstance(client, dict):
        raise ManifestValidationError("'client' must be an object")

    base_url = client.get("base_url")
    if not isinstance(base_url, str) or not base_url.strip():
        raise ManifestValidationError("'client.base_url' must be a non-empty string")

    auth = client.get("auth")
    if auth is not None:
        if not isinstance(auth, dict):
            raise ManifestValidationError("'client.auth' must be an object")
        auth_type = auth.get("type")
        if auth_type not in ALLOWED_AUTH_TYPES:
            raise ManifestValidationError(
                f"'client.auth.type' must be one of {sorted(ALLOWED_AUTH_TYPES)} (got {auth_type!r})"
            )

    resources = manifest["resources"]
    if not isinstance(resources, list) or not resources:
        raise ManifestValidationError("'resources' must be a non-empty list")

    seen_names: set[str] = set()
    for index, resource in enumerate(resources):
        if not isinstance(resource, dict):
            raise ManifestValidationError(f"Resource at index {index} must be an object")

        name = resource.get("name")
        if not isinstance(name, str) or not name:
            raise ManifestValidationError(f"Resource at index {index} is missing a 'name'")
        if name in seen_names:
            raise ManifestValidationError(f"Duplicate resource name: {name!r}")
        seen_names.add(name)

        endpoint = resource.get("endpoint")
        if not isinstance(endpoint, dict):
            raise ManifestValidationError(f"Resource {name!r} is missing an 'endpoint' object")

        path = endpoint.get("path")
        if not isinstance(path, str) or not path:
            raise ManifestValidationError(f"Resource {name!r} is missing 'endpoint.path'")

        method = endpoint.get("method")
        if method is not None:
            method_upper = method.upper() if isinstance(method, str) else None
            if method_upper not in ALLOWED_HTTP_METHODS:
                raise ManifestValidationError(
                    f"Resource {name!r}: 'endpoint.method' must be one of {sorted(ALLOWED_HTTP_METHODS)}"
                )


def validate_manifest_urls(manifest: dict[str, Any], team_id: int) -> tuple[bool, str | None]:
    """Walk every URL field in the manifest and reject internal/private hosts.

    Also enforces ``https://`` on PostHog Cloud. Self-hosted instances skip
    the host check via :func:`is_http_host_safe` (which is itself a no-op
    outside of cloud).
    """
    base_url = manifest["client"]["base_url"]
    ok, err = _check_url(base_url, team_id)
    if not ok:
        return False, f"Invalid base_url: {err}"

    for resource in manifest["resources"]:
        path = resource.get("endpoint", {}).get("path", "")
        if path.startswith(("http://", "https://")):
            ok, err = _check_url(path, team_id)
            if not ok:
                return False, f"Resource {resource['name']!r}: {err}"

    return True, None


def _check_url(url: str, team_id: int) -> tuple[bool, str | None]:
    parsed = urlparse(url)
    if not parsed.hostname:
        return False, f"URL {url!r} is missing a hostname"
    if is_cloud() and parsed.scheme != "https":
        return False, f"URL {url!r} must use https:// on PostHog Cloud"
    return is_http_host_safe(parsed.hostname, team_id)
