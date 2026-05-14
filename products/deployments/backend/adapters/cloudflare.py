"""Cloudflare Pages adapter boundary.

Declares the Protocol the rest of the product depends on, a Null stub
for tests and dev, and `CloudflarePagesAdapter` — the real implementation
that calls the Cloudflare Pages REST API. The resolver
`get_cloudflare_adapter()` returns the Null stub unless
`DEPLOYMENTS_CLOUDFLARE_ADAPTER` is wired to point at the real class,
which happens via chart values once the API token is in place.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol

from django.conf import settings

import requests
import structlog

# Tight timeout — `create_project` runs synchronously on the public POST
# /deployment_projects/ request path. Anything longer hurts user-visible
# latency more than it helps a flaky CF response.
CLOUDFLARE_API_TIMEOUT_SECONDS = 10
CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"
HOG_DEV_ZONE = "hog.dev"

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CFProject:
    """Minimal Cloudflare Pages project descriptor we depend on."""

    name: str
    subdomain: str


@dataclass(frozen=True)
class CFDeployment:
    """Minimal Cloudflare Pages deployment descriptor we depend on."""

    id: str
    url: str


class CloudflareAdapter(Protocol):
    """Surface we depend on from Cloudflare Pages.

    `create_project` is called synchronously from the public POST
    /deployment_projects/ handler, BEFORE the DB write — see
    deployments.md "Provisioning flow" and CLAUDE.md ("Avoid performing
    irreversible side effects inside an atomic block").

    `rollback` is called from the build worker when a rollback-trigger
    deployment lands; not from our process. We declare it here so the
    Protocol mirrors the full Cloudflare surface area.
    """

    def create_project(self, *, name: str, production_branch: str) -> CFProject: ...

    def rollback(self, *, project_name: str, deployment_id: str) -> CFDeployment: ...


class CloudflareError(Exception):
    """Raised when a Cloudflare API call fails. Surfaced as 502 by the viewset."""


class NullCloudflareAdapter:
    """Stub used in tests and the dev environment.

    `create_project` returns a synthetic CFProject whose name matches what
    the real API would assign. `rollback` is a no-op that echoes its input.
    """

    def create_project(self, *, name: str, production_branch: str) -> CFProject:
        return CFProject(name=name, subdomain=f"{name}.pages.dev")

    def rollback(self, *, project_name: str, deployment_id: str) -> CFDeployment:
        return CFDeployment(id=deployment_id, url=f"https://{project_name}.pages.dev")


class CloudflarePagesAdapter:
    """Cloudflare Pages adapter backed by the real REST API.

    Resolves settings lazily (at call time, not import time) so missing
    env vars only blow up when the adapter is actually exercised. This
    keeps test environments and the Null path unaffected by the real
    adapter's deployment-dependent config.

    `create_project` creates the Pages project and attaches a custom
    domain under `hog.dev` in a single call sequence. The custom domain
    attachment relies on the `hog.dev` zone living in the same CF
    account as the project — Cloudflare then auto-creates the CNAME
    record in the zone, so DNS records aren't managed from this side.
    """

    def _config(self) -> tuple[str, str, str]:
        account_id = getattr(settings, "DEPLOYMENTS_CLOUDFLARE_ACCOUNT_ID", "")
        api_token = getattr(settings, "DEPLOYMENTS_CLOUDFLARE_API_TOKEN", "")
        project_prefix = getattr(settings, "DEPLOYMENTS_CLOUDFLARE_PROJECT_PREFIX", "")
        if not account_id or not api_token:
            raise CloudflareError(
                "CloudflarePagesAdapter is missing required settings: "
                "DEPLOYMENTS_CLOUDFLARE_ACCOUNT_ID and DEPLOYMENTS_CLOUDFLARE_API_TOKEN."
            )
        return account_id, api_token, project_prefix

    def _request(self, method: str, path: str, *, api_token: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{CLOUDFLARE_API_BASE}{path}"
        headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
        try:
            response = requests.request(method, url, headers=headers, json=json, timeout=CLOUDFLARE_API_TIMEOUT_SECONDS)
        except requests.RequestException as err:
            # Path contains the CF account ID and is logged internally
            # for ops, but is intentionally kept out of the exception
            # message — `CloudflareError` is rendered into the public
            # 502 response body by the viewset.
            logger.warning("cloudflare_api_network_error", method=method, path=path, error=str(err))
            raise CloudflareError(f"Cloudflare API request failed: {err}") from err

        try:
            body = response.json()
        except ValueError as err:
            logger.warning("cloudflare_api_non_json_response", method=method, path=path, status=response.status_code)
            raise CloudflareError(
                f"Cloudflare API returned non-JSON response (status {response.status_code})."
            ) from err

        if not response.ok or not body.get("success", False):
            errors = body.get("errors") or []
            # Fall back to "Unknown error" rather than letting `None` slip
            # into the user-facing message when the error dict is missing
            # `"message"` (or `response.reason` is None for a malformed
            # response).
            message = (
                errors[0].get("message", "Unknown error")
                if errors and isinstance(errors[0], dict)
                else (response.reason or "Unknown error")
            )
            logger.warning(
                "cloudflare_api_call_failed",
                method=method,
                path=path,
                status=response.status_code,
                message=message,
            )
            raise CloudflareError(f"Cloudflare API call failed: {message} (status {response.status_code})")

        result = body.get("result")
        if not isinstance(result, dict):
            logger.warning("cloudflare_api_unexpected_result_shape", method=method, path=path)
            raise CloudflareError("Cloudflare API returned an unexpected result shape.")
        return result

    def create_project(self, *, name: str, production_branch: str) -> CFProject:
        account_id, api_token, project_prefix = self._config()
        cf_project_name = f"{project_prefix}{name}"
        create_path = f"/accounts/{account_id}/pages/projects"
        project_path = f"{create_path}/{cf_project_name}"

        self._request(
            "POST",
            create_path,
            api_token=api_token,
            json={"name": cf_project_name, "production_branch": production_branch},
        )

        # Attach the customer-facing `<name>.hog.dev` custom domain. CF
        # creates the CNAME in the hog.dev zone automatically because the
        # zone and the project live in the same account. The CF Pages
        # project's own `*.pages.dev` URL still works, but `subdomain`
        # below is what the product surfaces to the user.
        custom_domain = f"{name}.{HOG_DEV_ZONE}"
        try:
            self._request("POST", f"{project_path}/domains", api_token=api_token, json={"name": custom_domain})
        except CloudflareError:
            # The project create succeeded but the domain attach failed.
            # The CF project name is deterministic (`{prefix}{team_id}-{slug}`),
            # so leaving the orphan would block the user's next retry with
            # "Project name already taken". Best-effort cleanup; if the
            # delete itself fails we still surface the original error.
            try:
                self._request("DELETE", project_path, api_token=api_token)
            except CloudflareError as cleanup_err:
                logger.warning(
                    "cloudflare_orphan_cleanup_failed",
                    project=cf_project_name,
                    error=str(cleanup_err),
                )
            raise

        return CFProject(name=cf_project_name, subdomain=custom_domain)

    def rollback(self, *, project_name: str, deployment_id: str) -> CFDeployment:
        account_id, api_token, _ = self._config()
        result = self._request(
            "POST",
            f"/accounts/{account_id}/pages/projects/{project_name}/deployments/{deployment_id}/rollback",
            api_token=api_token,
        )
        # The rollback endpoint returns a deployment object. `url` is the
        # public URL of the deployment that's now serving production.
        url = result.get("url")
        if not isinstance(url, str) or not url:
            raise CloudflareError("Cloudflare rollback succeeded but returned no deployment URL.")
        new_deployment_id = result.get("id")
        if not isinstance(new_deployment_id, str) or not new_deployment_id:
            raise CloudflareError("Cloudflare rollback succeeded but returned no deployment id.")
        return CFDeployment(id=new_deployment_id, url=url)


def get_cloudflare_adapter() -> CloudflareAdapter:
    """Resolve the adapter implementation from settings.

    Reads `settings.DEPLOYMENTS_CLOUDFLARE_ADAPTER` as a `"module.path:ClassName"`
    string; if unset, returns `NullCloudflareAdapter`. Wire the real
    implementation in by setting this env var to
    `products.deployments.backend.adapters.cloudflare:CloudflarePagesAdapter`.
    """
    path = getattr(settings, "DEPLOYMENTS_CLOUDFLARE_ADAPTER", None)
    if not path:
        return NullCloudflareAdapter()
    module_path, class_name = path.split(":")
    module = import_module(module_path)
    return getattr(module, class_name)()
