"""Provision a DeploymentProject + matching Cloudflare Pages project.

The Cloudflare call happens BEFORE the atomic DB write, never inside it.
Rationale (from CLAUDE.md): "Avoid performing irreversible side effects
inside an atomic block: if the transaction rolls back, those side effects
have already happened." A rolled-back DB write doesn't un-create the
Cloudflare project. Putting the call inside `transaction.on_commit` is
worse — the HTTP response has already been written by the time the
callback fires, so the 502 path becomes unreachable.

If the Cloudflare call fails, no local row exists; the orphaned-CF-project
risk is zero (there isn't one). If the local insert later loses a uniqueness
race, the orphaned CF project gets reaped by a periodic cleanup task
(deferred to v2).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from ..adapters import CloudflareAdapter, get_cloudflare_adapter
from ..models import DeploymentProject


@dataclass(frozen=True)
class ProvisionInput:
    team_id: int
    created_by_id: int | None
    name: str
    slug: str
    repo_url: str
    default_branch: str
    github_integration_id: int | None
    github_repo_id: int | None
    build_command: str | None
    output_dir: str
    framework: str | None
    inject_posthog_snippet: bool


def execute(
    payload: ProvisionInput,
    *,
    cloudflare: CloudflareAdapter | None = None,
) -> DeploymentProject:
    cf = cloudflare or get_cloudflare_adapter()

    # 1) Irreversible CF side effect FIRST. If it fails, no DB row exists.
    cf_project = cf.create_project(
        name=f"{payload.team_id}-{payload.slug}",
        production_branch=payload.default_branch,
    )

    # 2) Narrow atomic block — local row only. Persist whatever the adapter
    # actually published the project at, not a hardcoded pattern: the slug
    # uniqueness constraint is per-team, so two different teams choosing
    # slug "myapp" would collide on a hardcoded `{slug}.posthog-app.com`,
    # and the value flows into the `$deployment` PostHog event so any
    # divergence pollutes analytics. The real adapter (when it lands) is
    # the source of truth for the actual subdomain.
    with transaction.atomic():
        project = DeploymentProject.objects.create(
            team_id=payload.team_id,
            created_by_id=payload.created_by_id,
            name=payload.name,
            slug=payload.slug,
            repo_url=payload.repo_url,
            default_branch=payload.default_branch,
            github_integration_id=payload.github_integration_id,
            github_repo_id=payload.github_repo_id,
            build_command=payload.build_command,
            output_dir=payload.output_dir,
            framework=payload.framework,
            inject_posthog_snippet=payload.inject_posthog_snippet,
            cloudflare_project_name=cf_project.name,
            subdomain=cf_project.subdomain,
            cloudflare_ready_at=timezone.now(),
        )
    return project
