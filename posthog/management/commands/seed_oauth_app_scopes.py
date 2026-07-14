from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.oauth import OAuthApplication
from posthog.scopes import ALL_SCOPES, DEFAULT_CEILING_SENTINEL, PRIVILEGED_SCOPES, effective_ceiling


def parse_scope_list(raw: str) -> list[str]:
    """Split a comma-separated ceiling into deduped, order-preserving entries."""
    seen: set[str] = set()
    result: list[str] = []
    for token in raw.split(","):
        entry = token.strip()
        if not entry or entry in seen:
            continue
        seen.add(entry)
        result.append(entry)
    return result


class Command(BaseCommand):
    help = (
        "Seed an OAuth application's scope ceiling (OAuthApplication.scopes) with a validated list. "
        "Every entry must be '@default' or a known obj:action scope; '*', typos, and unknown strings "
        "are rejected. A bad ceiling entry (e.g. '@defalt') would make wildcard narrowing treat the "
        "ceiling as an exhaustive allow-list and strip normal API scopes from existing clients, so "
        "this command validates before writing."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--client-id",
            required=True,
            help="client_id of the OAuthApplication to seed.",
        )
        parser.add_argument(
            "--scopes",
            required=True,
            help='Comma-separated scope ceiling, e.g. "@default,llm_gateway:read".',
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the planned change and effective ceiling without writing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        client_id: str = options["client_id"]
        dry_run: bool = options["dry_run"]

        new_scopes = parse_scope_list(options["scopes"])
        if not new_scopes:
            raise CommandError(
                "Refusing to seed an empty ceiling. Use the Django admin to intentionally clear an "
                "app's scopes; this command only seeds a non-empty ceiling."
            )

        invalid = [s for s in new_scopes if s != DEFAULT_CEILING_SENTINEL and s not in ALL_SCOPES]
        if invalid:
            raise CommandError(
                f"Invalid ceiling {'entry' if len(invalid) == 1 else 'entries'}: {invalid}. "
                f"Each entry must be '{DEFAULT_CEILING_SENTINEL}' or a known obj:action scope "
                f"(e.g. 'insight:read'); '*' is not a valid ceiling entry."
            )

        try:
            app = OAuthApplication.objects.get(client_id=client_id)
        except OAuthApplication.DoesNotExist:
            raise CommandError(f"No OAuthApplication found with client_id={client_id!r}.")

        ceiling = sorted(effective_ceiling(new_scopes))
        privileged = sorted(PRIVILEGED_SCOPES.intersection(ceiling))

        self.stdout.write(f"Application: {app.name} (client_id={client_id})")
        self.stdout.write(f"  current scopes:        {list(app.scopes)}")
        self.stdout.write(f"  new scopes:            {new_scopes}")
        self.stdout.write(f"  effective ceiling:     {len(ceiling)} scopes grantable")
        self.stdout.write(f"  privileged in ceiling: {privileged or 'none'}")

        if dry_run:
            self.stdout.write("Dry run: no changes written.")
            return

        app.scopes = new_scopes
        app.save(update_fields=["scopes"])
        self.stdout.write(self.style.SUCCESS(f"Seeded {app.name} scopes to {new_scopes}."))
