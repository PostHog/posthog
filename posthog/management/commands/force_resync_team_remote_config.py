"""
Force a synchronous re-sync of one or more teams' RemoteConfig.

Sister command to `sync_remote_configs` (which enqueues async Celery tasks for
every team). This one runs inline so support can confirm the result and propagate
to the hypercache + CDN purge immediately for a specific token. Use this when
`/array/<token>/config` is serving stale data and the team's organic post_save
signal chain has dropped the update.

Usage:
    python manage.py force_resync_team_remote_config --team-ids 12345
    python manage.py force_resync_team_remote_config --team-ids 12345 67890
    python manage.py force_resync_team_remote_config --api-tokens phc_abc123
"""

from django.core.management.base import BaseCommand, CommandError

import structlog

from posthog.models.remote_config import RemoteConfig
from posthog.models.team import Team

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Force-rebuild and re-publish RemoteConfig for one or more teams (synchronous)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-ids",
            nargs="+",
            type=int,
            default=None,
            help="Team IDs to resync.",
        )
        parser.add_argument(
            "--api-tokens",
            nargs="+",
            type=str,
            default=None,
            help="API tokens to resync (alternative to --team-ids).",
        )

    def handle(self, *args, **options):
        team_ids: list[int] | None = options["team_ids"]
        api_tokens: list[str] | None = options["api_tokens"]

        if not team_ids and not api_tokens:
            raise CommandError("Provide at least one of --team-ids or --api-tokens")

        teams_qs = Team.objects.all()
        filters = []
        if team_ids:
            filters.append(("ids", teams_qs.filter(id__in=team_ids)))
        if api_tokens:
            filters.append(("tokens", teams_qs.filter(api_token__in=api_tokens)))

        # Union the two filter queries by collecting IDs, then re-querying once.
        target_ids: set[int] = set()
        for _, qs in filters:
            target_ids.update(qs.values_list("id", flat=True))

        if not target_ids:
            raise CommandError("No matching teams found for the given selectors")

        succeeded = 0
        failed = 0
        for team in Team.objects.filter(id__in=target_ids):
            try:
                try:
                    remote_config = RemoteConfig.objects.get(team=team)
                except RemoteConfig.DoesNotExist:
                    # `config` is NOT NULL; sync() populates it before saving.
                    remote_config = RemoteConfig(team=team)
                remote_config.sync(force=True)
                succeeded += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"OK  team_id={team.id} token={team.api_token} (synced_at={remote_config.synced_at})"
                    )
                )
            except Exception as e:
                failed += 1
                logger.exception(
                    "force_resync_team_remote_config_failed",
                    team_id=team.id,
                    error=str(e),
                )
                self.stdout.write(self.style.ERROR(f"FAIL team_id={team.id} token={team.api_token}: {e}"))

        summary = f"Force-resync complete: succeeded={succeeded} failed={failed}"
        if failed:
            raise CommandError(summary)
        self.stdout.write(self.style.SUCCESS(summary))
