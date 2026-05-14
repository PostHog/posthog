"""Cloudflare Pages adapter boundary.

The Build/Infra stream owns the real implementation (a thin wrapper around
the Cloudflare Pages REST API). We declare the Protocol they implement
against and a Null stub for tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Protocol

from django.conf import settings


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


def get_cloudflare_adapter() -> CloudflareAdapter:
    """Resolve the adapter implementation from settings.

    Reads `settings.DEPLOYMENTS_CLOUDFLARE_ADAPTER` as a `"module.path:ClassName"`
    string; if unset, returns `NullCloudflareAdapter`. Build/Infra wires the
    real implementation by setting this env var.
    """
    path = getattr(settings, "DEPLOYMENTS_CLOUDFLARE_ADAPTER", None)
    if not path:
        return NullCloudflareAdapter()
    module_path, class_name = path.split(":")
    module = import_module(module_path)
    return getattr(module, class_name)()
