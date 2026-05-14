"""Seed fake agent applications, revisions, and sessions for local dev."""

from __future__ import annotations

import random
import hashlib
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from posthog.models.team import Team

from products.agent_stack.backend.enums import DeploymentStatus, RevisionState, SessionState
from products.agent_stack.backend.models import AgentApplication, AgentApplicationRevision, AgentApplicationSession

# Believable app names so the UI doesn't look like lorem ipsum.
SAMPLE_APPS = [
    ("standup-bot", "Standup bot", "Collects daily standups from Slack and summarises into a digest."),
    ("triage-bot", "Triage bot", "Watches the bug intake channel and routes new reports to the right team."),
    ("deploy-monitor", "Deploy monitor", "Tails CI events, surfaces failures, kicks off rollbacks on regressions."),
    ("inbox-zero", "Inbox zero", "Drafts replies to support tickets and posts them for human review."),
    ("oncall-buddy", "Oncall buddy", "Handles first-line alerts overnight, escalates when uncertain."),
]

SAMPLE_TRIGGER_TYPES = ["cron", "webhook", "slack", "api"]


def _hash(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _pick_revision_state() -> str:
    return random.choices(
        [
            RevisionState.READY,
            RevisionState.READY,
            RevisionState.READY,
            RevisionState.UPLOADED,
            RevisionState.FAILED,
            RevisionState.PENDING_UPLOAD,
        ],
        k=1,
    )[0]


def _pick_session_state() -> str:
    return random.choices(
        [
            SessionState.COMPLETED,
            SessionState.COMPLETED,
            SessionState.COMPLETED,
            SessionState.RUNNING,
            SessionState.FAILED,
            SessionState.CANCELED,
            SessionState.AVAILABLE,
        ],
        k=1,
    )[0]


class Command(BaseCommand):
    help = "Seed fake agent applications, revisions, and sessions for the given team."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, default=1, help="Team ID to seed (default: 1).")
        parser.add_argument(
            "--apps",
            type=int,
            default=len(SAMPLE_APPS),
            help=f"Number of apps to create, capped at {len(SAMPLE_APPS)} (default: all).",
        )
        parser.add_argument(
            "--revisions-per-app",
            type=int,
            default=4,
            help="Number of revisions per app (default: 4). One will be marked live.",
        )
        parser.add_argument(
            "--sessions-per-app",
            type=int,
            default=30,
            help="Number of sessions per app spread over the last 7 days (default: 30).",
        )
        parser.add_argument(
            "--wipe",
            action="store_true",
            help="Delete any existing seeded data for the team before reseeding.",
        )

    def handle(self, *_args, **options) -> None:
        team_id: int = options["team_id"]
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Team {team_id} not found"))
            return

        if options["wipe"]:
            deleted, _ = AgentApplication.objects.filter(team=team).delete()
            self.stdout.write(self.style.WARNING(f"Wiped {deleted} agent_stack rows for team {team.id}"))

        n_apps = min(options["apps"], len(SAMPLE_APPS))
        for slug, name, description in SAMPLE_APPS[:n_apps]:
            self._seed_app(
                team=team,
                slug=slug,
                name=name,
                description=description,
                revisions_per_app=options["revisions_per_app"],
                sessions_per_app=options["sessions_per_app"],
            )

        self.stdout.write(self.style.SUCCESS(f"Seeded {n_apps} agent applications for team {team.id}"))

    def _seed_app(
        self,
        *,
        team: Team,
        slug: str,
        name: str,
        description: str,
        revisions_per_app: int,
        sessions_per_app: int,
    ) -> None:
        app, created = AgentApplication.objects.get_or_create(
            team=team,
            slug=slug,
            defaults={
                "name": name,
                "description": description,
                "encrypted_env": "ANTHROPIC_API_KEY=sk-fake\nSLACK_BOT_TOKEN=xoxb-fake\nDATABASE_URL=postgres://fake",
            },
        )
        if not created:
            self.stdout.write(f"  {slug} already exists, refreshing revisions / sessions")

        revisions: list[AgentApplicationRevision] = []
        for i in range(revisions_per_app):
            state = _pick_revision_state() if i < revisions_per_app - 1 else RevisionState.READY
            rev = AgentApplicationRevision.objects.create(
                team=team,
                application=app,
                state=state,
                deployment_status=DeploymentStatus.DISABLED,
                bundle_sha256=_hash(f"{slug}-{i}"),
                bundle_size=random.randint(100_000, 5_000_000),
                top_level_config={"version": "v1", "agent_name": name},
            )
            # Backdate so the "list ready revisions" sort is interesting.
            AgentApplicationRevision.objects.filter(pk=rev.pk).update(
                created_at=timezone.now() - timedelta(days=revisions_per_app - i, hours=random.randint(0, 12)),
            )
            revisions.append(rev)

        ready = [r for r in revisions if r.state == RevisionState.READY]
        if ready:
            live = ready[-1]
            live.deployment_status = DeploymentStatus.LIVE
            live.save(update_fields=["deployment_status", "updated_at"])
            # Mark one earlier ready revision as a preview, just for visual variety.
            if len(ready) >= 2:
                preview = ready[0]
                preview.deployment_status = DeploymentStatus.PREVIEW
                preview.save(update_fields=["deployment_status", "updated_at"])

            for k in range(sessions_per_app):
                age_minutes = random.randint(1, 7 * 24 * 60)
                state = _pick_session_state()
                trigger = random.choice(SAMPLE_TRIGGER_TYPES)
                session_revision = random.choice(ready)
                session = AgentApplicationSession.objects.create(
                    team=team,
                    application=app,
                    revision=session_revision,
                    state=state,
                    trigger_type=trigger,
                    trigger_payload={"source": trigger, "session_index": k},
                    input={"prompt": "What's the status of yesterday's standup?"} if trigger == "slack" else {},
                )
                started_at = timezone.now() - timedelta(minutes=age_minutes)
                heartbeat_at = started_at + timedelta(seconds=random.randint(5, 600))
                completed_at = None
                if state in (SessionState.COMPLETED, SessionState.FAILED, SessionState.CANCELED):
                    completed_at = heartbeat_at + timedelta(seconds=random.randint(10, 600))
                AgentApplicationSession.objects.filter(pk=session.pk).update(
                    created_at=started_at,
                    started_at=started_at,
                    last_heartbeat_at=heartbeat_at,
                    completed_at=completed_at,
                )

        self.stdout.write(
            f"  {slug}: {len(revisions)} revisions, "
            f"live={'yes' if ready else 'no'}, "
            f"{sessions_per_app if ready else 0} sessions"
        )
