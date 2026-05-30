"""
Inspect or flip a team's llm-gateway admission state.

Usage:
    python manage.py llm_gateway_team enable 42
    python manage.py llm_gateway_team enable phc_demo
    python manage.py llm_gateway_team revoke 42
    python manage.py llm_gateway_team unrevoke 42
    python manage.py llm_gateway_team status 42

Both fields live on Team and project into the dedicated llm_gateway_policy
hypercache blob via Team.save() signal handlers. The gateway admits a team
only when enabled_at is set and revoked_at is null.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from posthog.models.team.team import Team


class Command(BaseCommand):
    help = "Inspect or flip a team's llm-gateway admission state (enabled_at, revoked_at)."

    def add_arguments(self, parser: Any) -> None:
        sub = parser.add_subparsers(dest="action", required=True, metavar="action")
        for verb, desc in (
            ("enable", "set llm_gateway_enabled_at to now (idempotent: no-op if already set)"),
            ("revoke", "set llm_gateway_revoked_at to now (idempotent: no-op if already set)"),
            ("unrevoke", "clear llm_gateway_revoked_at (no-op if already null)"),
            ("status", "print the team's current admission state"),
        ):
            p = sub.add_parser(verb, help=desc)
            p.add_argument("team", help="team id (integer) or api_token (phc_...)")

    def handle(self, *args: Any, **opts: Any) -> None:
        team = _resolve_team(opts["team"])
        action = opts["action"]
        if action == "status":
            _print_status(self.stdout, team)
            return

        before = _snapshot(team)
        changed = _apply(team, action)
        if not changed:
            self.stdout.write(f"team {team.id} ({team.api_token}): {action} no-op ({before})")
            return

        team.save()
        after = _snapshot(team)
        self.stdout.write(self.style.SUCCESS(f"team {team.id} ({team.api_token}): {action} ok"))
        self.stdout.write(f"  before: {before}")
        self.stdout.write(f"  after:  {after}")


def _resolve_team(arg: str) -> Team:
    if arg.startswith("phc_"):
        try:
            return Team.objects.get(api_token=arg)
        except Team.DoesNotExist:
            raise CommandError(f"no team with api_token={arg!r}")
    try:
        team_id = int(arg)
    except ValueError as e:
        raise CommandError(f"expected integer team_id or phc_ token, got {arg!r}") from e
    try:
        return Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        raise CommandError(f"no team with id={team_id}")


def _apply(team: Team, action: str) -> bool:
    """Mutate team in-place; return True if a save is required."""
    now = timezone.now()
    if action == "enable":
        if team.llm_gateway_enabled_at is not None:
            return False
        team.llm_gateway_enabled_at = now
        return True
    if action == "revoke":
        if team.llm_gateway_revoked_at is not None:
            return False
        team.llm_gateway_revoked_at = now
        return True
    if action == "unrevoke":
        if team.llm_gateway_revoked_at is None:
            return False
        team.llm_gateway_revoked_at = None
        return True
    raise CommandError(f"unknown action {action!r}")


def _snapshot(team: Team) -> str:
    return f"enabled_at={team.llm_gateway_enabled_at} revoked_at={team.llm_gateway_revoked_at}"


def _print_status(stdout: Any, team: Team) -> None:
    admit = team.llm_gateway_enabled_at is not None and team.llm_gateway_revoked_at is None
    state = "admit" if admit else "deny"
    stdout.write(f"team {team.id} ({team.api_token}) state={state}")
    stdout.write(f"  enabled_at: {team.llm_gateway_enabled_at}")
    stdout.write(f"  revoked_at: {team.llm_gateway_revoked_at}")
