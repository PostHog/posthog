from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.organization import Organization
from posthog.models.utils import slug_matches_base


class Command(BaseCommand):
    help = "Regenerate one organization's slug from its current name, to repair a slug left behind by an older rename"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("organization", help="Organization UUID or current slug")
        parser.add_argument("--live-run", action="store_true", help="Apply the change (default is dry-run)")

    def handle(self, *args: Any, **options: Any) -> None:
        organization = get_organization(options["organization"])
        base_slug = organization.slug_from_name
        if not base_slug:
            raise CommandError(f"The name of organization {organization.id} gives an empty slug")

        if slug_matches_base(organization.slug, base_slug):
            self.stdout.write(f"Slug '{organization.slug}' already matches the name '{organization.name}'")
            return

        if not options["live_run"]:
            self.stdout.write(
                f"Would change slug '{organization.slug}' to '{base_slug}', "
                "or to a suffixed variant if that slug is taken"
            )
            self.stdout.write(self.style.NOTICE("Run with --live-run to apply the change"))
            return

        previous_slug = organization.slug
        organization.repair_slug()
        self.stdout.write(self.style.SUCCESS(f"Changed slug '{previous_slug}' to '{organization.slug}'"))


def get_organization(identifier: str) -> Organization:
    try:
        organization_id = UUID(identifier)
    except ValueError:
        organization = Organization.objects.filter(slug=identifier).first()
    else:
        organization = Organization.objects.filter(id=organization_id).first()
    if organization is None:
        raise CommandError(f"No organization found for '{identifier}'")
    return organization
