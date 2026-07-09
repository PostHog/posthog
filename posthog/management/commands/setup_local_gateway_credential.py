"""
Provision the deterministic local ai-gateway dev credential, end to end:

  1. admit the team to the gateway (delegates to `llm_gateway_team`)
  2. upsert the `phs_` project-secret key (scope ``llm_gateway:read``)
  3. publish its credential blob to the gateway's Redis, synchronously

so `bin/start gateway` (resolver mode) authenticates with no manual setup.
Dev/CI only — refuses against a cloud deployment. Idempotent: re-runs upsert
the key and re-publish the blob. Driven by ``bin/setup-gateway-e2e``; lives here
(rather than an inline ``manage.py shell`` heredoc) so it's unit-testable.

    AI_GATEWAY_REDIS_URL=redis://localhost:6381 \
        python manage.py setup_local_gateway_credential --phs phs_... [--team 42]

``AI_GATEWAY_REDIS_URL`` must point at the gateway's Redis so the blob lands
where the gateway reads it; without it the publish is a no-op (settings gate).
"""

from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from posthog.management.commands.llm_gateway_team import _resolve_team
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team.team import Team
from posthog.models.utils import hash_key_value, mask_key_value
from posthog.storage.gateway_credential_cache import project_gateway_credential

_LABEL = "local-gateway-e2e"
_SCOPES = ["llm_gateway:read"]

# Emitted on the last line; bin/setup-gateway-e2e greps for it to learn which
# team was provisioned (the script also funds that team's gateway ledger).
TEAM_ID_MARKER = "__GATEWAY_E2E_TEAM_ID__"


class Command(BaseCommand):
    help = "Provision the local ai-gateway dev credential (enable team + phs_ + blob). Dev/CI only."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--phs", required=True, help="deterministic dev phs_ bearer to provision")
        parser.add_argument("--team", help="team id or api_token (default: the lowest-pk team)")

    def handle(self, *args: Any, **opts: Any) -> None:
        if settings.CLOUD_DEPLOYMENT:
            raise CommandError("refusing to run against a cloud deployment")

        phs: str = opts["phs"]
        team = _resolve_team(opts["team"]) if opts.get("team") else _first_team()

        # Admit the team to the gateway. Reuse the canonical command rather than
        # re-touching enabled_at / revoked_at here: enable (idempotent) + clear
        # any prior revoke. The gateway admits only when enabled and not revoked.
        call_command("llm_gateway_team", "enable", str(team.id), stdout=self.stdout)
        call_command("llm_gateway_team", "unrevoke", str(team.id), stdout=self.stdout)

        secure = hash_key_value(phs)
        key, _created = ProjectSecretAPIKey.objects.get_or_create(
            team=team,
            label=_LABEL,
            defaults={"secure_value": secure, "mask_value": mask_key_value(phs), "scopes": _SCOPES},
        )
        changed: list[str] = []
        if key.secure_value != secure:
            key.secure_value, key.mask_value = secure, mask_key_value(phs)
            changed += ["secure_value", "mask_value"]
        if key.scopes != _SCOPES:
            key.scopes = _SCOPES
            changed.append("scopes")
        if changed:
            key.save(update_fields=changed)

        # Publish synchronously — don't depend on a running Celery worker locally.
        project_gateway_credential(key)

        self.stdout.write(f"{TEAM_ID_MARKER}={team.id}")


def _first_team() -> Team:
    team = Team.objects.order_by("pk").first()
    if team is None:
        raise CommandError("no team in the local db — bootstrap one first")
    return team
