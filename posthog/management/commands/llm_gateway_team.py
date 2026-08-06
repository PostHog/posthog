"""
Inspect or flip a team's llm-gateway admission state.

Usage:
    python manage.py llm_gateway_team enable 42
    python manage.py llm_gateway_team enable phc_demo
    python manage.py llm_gateway_team unenable 42
    python manage.py llm_gateway_team revoke 42
    python manage.py llm_gateway_team unrevoke 42
    python manage.py llm_gateway_team set-allowance 42 5
    python manage.py llm_gateway_team clear-allowance 42
    python manage.py llm_gateway_team refresh 42
    python manage.py llm_gateway_team status 42

The admission fields and llm_gateway_overspend_allowance_usd live on Team.
enabled_at/revoked_at project into the dedicated llm_gateway_policy blob;
llm_gateway_overspend_allowance_usd projects into each credential's gateway_credential
blob (under the wire key overspend_allowance_usd). Both flow through Team.save() signal
handlers. The gateway admits a team only when enabled_at is set and revoked_at is null.
"""

from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from posthog.models.team.team import Team
from posthog.storage.gateway_credential_cache import validate_overspend_allowance_usd
from posthog.storage.team_llm_gateway_policy_cache import update_team_llm_gateway_policy_cache

_VERBS = (
    ("enable", "set llm_gateway_enabled_at to now (idempotent: no-op if already set)"),
    ("unenable", "clear llm_gateway_enabled_at (no-op if already null)"),
    ("revoke", "set llm_gateway_revoked_at to now (idempotent: no-op if already set)"),
    ("unrevoke", "clear llm_gateway_revoked_at (no-op if already null)"),
    ("set-allowance", "set llm_gateway_overspend_allowance_usd (USD, 0–10000, max 6 dp)"),
    ("clear-allowance", "clear llm_gateway_overspend_allowance_usd (unset → gateway falls back to its default)"),
    ("refresh", "rewrite the team's policy cache entry from current DB state (no field change)"),
    ("status", "print the team's current admission state"),
)


class Command(BaseCommand):
    help = "Inspect or flip a team's llm-gateway admission state (enabled_at, revoked_at)."

    def add_arguments(self, parser: Any) -> None:
        sub = parser.add_subparsers(dest="action", required=True, metavar="action")
        for verb, desc in _VERBS:
            p = sub.add_parser(verb, help=desc)
            p.add_argument("team", help="team id (integer) or api_token")
            if verb == "set-allowance":
                p.add_argument("usd", help="allowance in USD, e.g. 5 or 5.000000 (0–10000, max 6 dp)")

    def handle(self, *args: Any, **opts: Any) -> None:
        team = _resolve_team(opts["team"])
        action = opts["action"]
        if action == "status":
            _print_status(self.stdout, team)
            return
        if action == "refresh":
            update_team_llm_gateway_policy_cache(team)
            self.stdout.write(self.style.SUCCESS(f"team {team.id} ({team.api_token}): refresh ok"))
            self.stdout.write(f"  {_snapshot(team)}")
            return

        if action == "set-allowance":
            canonical_id = team.parent_team_id or team.id
            if canonical_id != team.id:
                raise CommandError(
                    f"team {team.id} is a child environment; set the allowance on its project-root "
                    f"team {canonical_id} — the gateway projection reads it from there, not the child"
                )
        allowance = _parse_allowance(opts["usd"]) if action == "set-allowance" else None

        before = _snapshot(team)
        changed = _apply(team, action, allowance)
        if not changed:
            self.stdout.write(f"team {team.id} ({team.api_token}): {action} no-op ({before})")
            return

        team.save()
        after = _snapshot(team)
        self.stdout.write(self.style.SUCCESS(f"team {team.id} ({team.api_token}): {action} ok"))
        self.stdout.write(f"  before: {before}")
        self.stdout.write(f"  after:  {after}")


def _resolve_team(arg: str) -> Team:
    # Bare integers resolve as id; anything else as api_token (no phc_ prefix
    # gate, since BaseTest fixtures use non-prefixed tokens).
    try:
        team_id = int(arg)
    except ValueError:
        try:
            return Team.objects.get(api_token=arg)
        except Team.DoesNotExist:
            raise CommandError(f"no team with api_token={arg!r}")
    try:
        return Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        raise CommandError(f"no team with id={team_id}")


def _parse_allowance(raw: str) -> Decimal:
    try:
        return validate_overspend_allowance_usd(Decimal(raw))
    except InvalidOperation:
        raise CommandError(f"invalid allowance {raw!r}: not a number")
    except ValueError as e:
        raise CommandError(f"invalid allowance {raw!r}: {e}")


def _apply(team: Team, action: str, allowance: Decimal | None) -> bool:
    """Mutate team in-place; return True if a save is required."""
    now = timezone.now()
    if action == "enable":
        if team.llm_gateway_enabled_at is not None:
            return False
        team.llm_gateway_enabled_at = now
        return True
    if action == "unenable":
        if team.llm_gateway_enabled_at is None:
            return False
        team.llm_gateway_enabled_at = None
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
    if action == "set-allowance":
        if team.llm_gateway_overspend_allowance_usd == allowance:
            return False
        team.llm_gateway_overspend_allowance_usd = allowance
        return True
    if action == "clear-allowance":
        if team.llm_gateway_overspend_allowance_usd is None:
            return False
        team.llm_gateway_overspend_allowance_usd = None
        return True
    raise CommandError(f"unknown action {action!r}")


def _snapshot(team: Team) -> str:
    return (
        f"enabled_at={team.llm_gateway_enabled_at} revoked_at={team.llm_gateway_revoked_at} "
        f"overspend_allowance_usd={team.llm_gateway_overspend_allowance_usd}"
    )


def _print_status(stdout: Any, team: Team) -> None:
    admit = team.llm_gateway_enabled_at is not None and team.llm_gateway_revoked_at is None
    state = "admit" if admit else "deny"
    stdout.write(f"team {team.id} ({team.api_token}) state={state}")
    stdout.write(f"  enabled_at: {team.llm_gateway_enabled_at}")
    stdout.write(f"  revoked_at: {team.llm_gateway_revoked_at}")
    stdout.write(f"  overspend_allowance_usd: {team.llm_gateway_overspend_allowance_usd}")
