"""`manage.py seed_deployments` — generate realistic dev data.

Populates the list scene with a `DeploymentProject` + ~25 mixed-status
`Deployment` rows + 3-5 `DeploymentEvent` rows per deployment for the
team passed via `--team-id`. Idempotent: deletes the slug's previous
seed rows (anything with `trigger_kind=seed`) before re-creating them.

Run locally with:

    python manage.py seed_deployments --team-id <id>

To create multiple seed projects (different repos):

    python manage.py seed_deployments --team-id <id> --project-count 3
"""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from ...domain.trigger import TriggerKind
from ...models import Deployment, DeploymentEvent, DeploymentProject

# Deterministic content sources for realistic-looking seed rows. The same
# pool every run so the list view is recognisable across iterations.
SEED_COMMIT_MESSAGES = [
    "feat: add new pricing tile to marketing site",
    "fix: rebroadcast on-boarding emails when SMTP recovers",
    "chore: bump next.js to 14.2.5",
    "feat: surface deploy logs in the new pipeline tab",
    "fix: stop double-firing analytics event on hero CTA",
    "refactor: extract <PreviewCard> from <DeploymentList>",
    "feat: dark-mode polish on the docs landing page",
    "fix: regression where /pricing showed stale data",
    "chore: regenerate posthog-js bundle",
    "feat: hide cancelled deploys behind the status filter",
    "fix: typo on the changelog header",
    "feat: support `astro` framework auto-detect",
    "chore: upgrade tailwindcss to 3.4",
    "fix: rollback button stuck disabled after redeploy",
    "feat: render preview screenshot on the current-deployment card",
]
SEED_AUTHORS = [
    ("Alice Chen", "alice@example.com"),
    ("Bob Patel", "bob@example.com"),
    ("Carmen Vasquez", "carmen@example.com"),
    ("Dmitri Kuznetsov", "dmitri@example.com"),
    ("Erin O'Hara", "erin@example.com"),
]
SEED_PROJECTS = [
    ("Marketing site", "marketing-site", "https://github.com/example-org/marketing-site"),
    ("Customer dashboard", "customer-dashboard", "https://github.com/example-org/customer-dashboard"),
    ("Docs site", "docs-site", "https://github.com/example-org/docs-site"),
]
# Roughly Vercel-like distribution: mostly green, a handful red, the rest in-flight or cancelled.
STATUS_DISTRIBUTION: list[tuple[Deployment.Status, int]] = [
    (Deployment.Status.READY, 16),
    (Deployment.Status.ERROR, 5),
    (Deployment.Status.CANCELLED, 2),
    (Deployment.Status.BUILDING, 1),
    (Deployment.Status.QUEUED, 1),
]
ERROR_STEPS: list[Deployment.ErrorStep] = [
    Deployment.ErrorStep.BUILD,
    Deployment.ErrorStep.INSTALL,
    Deployment.ErrorStep.PUBLISH,
    Deployment.ErrorStep.CLONE,
]


class Command(BaseCommand):
    help = "Seed mock deployments for local development."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID to attach the seed rows to.",
        )
        parser.add_argument(
            "--project-count",
            type=int,
            default=1,
            help=f"Number of DeploymentProject rows to create (default: 1, max: {len(SEED_PROJECTS)}).",
        )
        parser.add_argument(
            "--deployments-per-project",
            type=int,
            default=25,
            help="Approximate number of Deployment rows per project (default: 25).",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=42,
            help="Random seed for deterministic generation (default: 42).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        project_count: int = min(options["project_count"], len(SEED_PROJECTS))
        deployments_per_project: int = options["deployments_per_project"]
        rng = random.Random(options["seed"])

        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Team {team_id} not found."))
            return

        with team_scope(team.id):
            for idx in range(project_count):
                name, slug, repo_url = SEED_PROJECTS[idx]
                project = self._upsert_project(team_id=team.id, name=name, slug=slug, repo_url=repo_url)
                self._clear_seed_deployments(project)
                deployments = self._create_deployments(
                    project=project,
                    count=deployments_per_project,
                    rng=rng,
                )
                self._link_current_deployment(project, deployments)
                self.stdout.write(
                    self.style.SUCCESS(f"Seeded project '{name}' (slug={slug}) with {len(deployments)} deployments.")
                )

    def _upsert_project(self, *, team_id: int, name: str, slug: str, repo_url: str) -> DeploymentProject:
        defaults = {
            "name": name,
            "repo_url": repo_url,
            "default_branch": "main",
            # build_command left null — the framework hint below is the
            # canonical way to tell the worker how to build a Vite app.
            "output_dir": "dist",
            "framework": "vite",
            "inject_posthog_snippet": False,
            "cloudflare_project_name": f"{team_id}-{slug}",
            "subdomain": f"{slug}.posthog-app.com",
            "cloudflare_ready_at": timezone.now(),
        }
        project, _ = DeploymentProject.objects.update_or_create(team_id=team_id, slug=slug, defaults=defaults)
        return project

    def _clear_seed_deployments(self, project: DeploymentProject) -> None:
        # Wipe ALL deployments on this seed-owned project. The seed mixes
        # `SEED` and `REDEPLOY` trigger kinds (~15% of rows are REDEPLOY)
        # so filtering on `trigger_kind=SEED` would leak REDEPLOY rows
        # across runs. Cascade also wipes the project's DeploymentEvent
        # rows.
        Deployment.objects.filter(project=project).delete()

    def _create_deployments(
        self,
        *,
        project: DeploymentProject,
        count: int,
        rng: random.Random,
    ) -> list[Deployment]:
        plan = self._expand_status_distribution(count, rng)
        now = timezone.now()
        deployments: list[Deployment] = []

        # Walk backwards in time so the most recent rows land at the top
        # of the list when sorted by -created_at.
        for offset, target_status in enumerate(plan):
            created_at = now - timedelta(hours=offset * 3 + rng.randint(0, 90))
            commit_msg = rng.choice(SEED_COMMIT_MESSAGES)
            author_name, author_email = rng.choice(SEED_AUTHORS)
            commit_sha = self._random_sha(rng)

            started_at = None
            finished_at = None
            error_message = ""
            error_step = ""
            deployment_url = ""
            cloudflare_deployment_id = ""

            if target_status in (
                Deployment.Status.READY,
                Deployment.Status.ERROR,
                Deployment.Status.CANCELLED,
                Deployment.Status.BUILDING,
            ):
                started_at = created_at + timedelta(seconds=rng.randint(2, 8))
            if target_status in (
                Deployment.Status.READY,
                Deployment.Status.ERROR,
                Deployment.Status.CANCELLED,
            ):
                # Narrow `started_at`: every status that sets `finished_at` is also in
                # the (READY|ERROR|CANCELLED|BUILDING) set above where `started_at` was set.
                assert started_at is not None
                finished_at = started_at + timedelta(seconds=rng.randint(45, 240))
            if target_status == Deployment.Status.READY:
                deployment_url = f"https://{commit_sha[:7]}.{project.subdomain}"
                cloudflare_deployment_id = f"cf-{commit_sha[:12]}"
            if target_status == Deployment.Status.ERROR:
                error_step_choice = rng.choice(ERROR_STEPS)
                error_step = error_step_choice.value
                error_message = self._error_message_for(error_step_choice)

            # Most deployments are user-triggered; sprinkle in a couple
            # of redeploys against earlier rows to exercise the redeploy
            # filter.
            trigger_kind = TriggerKind.SEED.value
            triggered_by_deployment = None
            if offset > 0 and rng.random() < 0.15:
                trigger_kind = TriggerKind.REDEPLOY.value
                if deployments:
                    triggered_by_deployment = rng.choice(deployments)

            deployment = Deployment.objects.create(
                project=project,
                team_id=project.team_id,
                status=target_status.value,
                started_at=started_at,
                finished_at=finished_at,
                commit_sha=commit_sha,
                commit_message=commit_msg,
                commit_author_name=author_name,
                commit_author_email=author_email,
                repo_url=project.repo_url,
                branch=project.default_branch,
                deployment_url=deployment_url,
                error_message=error_message,
                error_step=error_step,
                cloudflare_deployment_id=cloudflare_deployment_id,
                trigger_kind=trigger_kind,
                triggered_by_deployment=triggered_by_deployment,
            )
            # auto_now_add overwrites created_at on insert, so fix it up
            # with an explicit update so the list view is chronological.
            Deployment.objects.filter(pk=deployment.pk).update(created_at=created_at)
            deployment.created_at = created_at

            self._create_events_for(deployment, rng)
            deployments.append(deployment)

        return deployments

    @staticmethod
    def _expand_status_distribution(count: int, rng: random.Random) -> list[Deployment.Status]:
        # Scale the configured distribution to the requested row count,
        # then shuffle so the timeline mixes statuses naturally.
        total = sum(weight for _, weight in STATUS_DISTRIBUTION)
        plan: list[Deployment.Status] = []
        for s, weight in STATUS_DISTRIBUTION:
            plan.extend([s] * max(1, round(weight * count / total)))
        # Pad / trim to exactly `count`.
        while len(plan) < count:
            plan.append(Deployment.Status.READY)
        plan = plan[:count]
        rng.shuffle(plan)
        return plan

    @staticmethod
    def _random_sha(rng: random.Random) -> str:
        return "".join(rng.choice("0123456789abcdef") for _ in range(40))

    @staticmethod
    def _error_message_for(step: Deployment.ErrorStep) -> str:
        match step:
            case Deployment.ErrorStep.CLONE:
                return "fatal: repository not found"
            case Deployment.ErrorStep.INSTALL:
                return "ERR_PNPM_FETCH_404 GET https://registry.npmjs.org/ghost-pkg: not_found"
            case Deployment.ErrorStep.BUILD:
                return "Error: Type 'string | undefined' is not assignable to type 'string'."
            case Deployment.ErrorStep.PUBLISH:
                return "wrangler: Error 1019: Request blocked by Cloudflare access policy"
            case _:
                return "Build failed."

    def _create_events_for(self, deployment: Deployment, rng: random.Random) -> None:
        events: list[tuple[str, dict[str, Any]]] = [
            ("dispatched", {"trigger_kind": deployment.trigger_kind}),
            (
                "status_changed",
                {"from": Deployment.Status.QUEUED.value, "to": Deployment.Status.INITIALIZING.value},
            ),
        ]
        if deployment.status not in (Deployment.Status.QUEUED, Deployment.Status.CANCELLED):
            events.append(
                (
                    "status_changed",
                    {"from": Deployment.Status.INITIALIZING.value, "to": Deployment.Status.BUILDING.value},
                )
            )
        if deployment.status == Deployment.Status.READY:
            events.append(("status_changed", {"from": Deployment.Status.BUILDING.value, "to": "ready"}))
            events.append(("preview_captured", {"url": deployment.deployment_url}))
        elif deployment.status == Deployment.Status.ERROR:
            events.append(
                (
                    "status_changed",
                    {
                        "from": Deployment.Status.BUILDING.value,
                        "to": "error",
                        "error_step": deployment.error_step,
                    },
                )
            )
        elif deployment.status == Deployment.Status.CANCELLED:
            events.append(("status_changed", {"to": "cancelled", "by": "user"}))

        for event_type, payload in events:
            DeploymentEvent.objects.create(
                deployment_id=deployment.pk,
                team_id=deployment.team_id,
                event_type=event_type,
                payload=payload,
            )

    def _link_current_deployment(self, project: DeploymentProject, deployments: list[Deployment]) -> None:
        # Pick the most recent READY row as the live deployment.
        latest_ready = next(
            (d for d in deployments if d.status == Deployment.Status.READY.value),
            None,
        )
        if latest_ready is not None:
            project.current_deployment = latest_ready
            project.save(update_fields=["current_deployment", "updated_at"])
