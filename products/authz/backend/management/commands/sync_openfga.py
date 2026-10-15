from typing import cast
from uuid import UUID

from django.core.management.base import BaseCommand, CommandParser

from products.authz.backend.facade import api


class Command(BaseCommand):
    help = "Reconcile organization authorization data into OpenFGA."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("organization_ids", nargs="+", type=UUID)

    def handle(self, *args: object, **options: object) -> None:
        for organization_id in cast(list[UUID], options["organization_ids"]):
            api.synchronize_organization(organization_id)
            self.stdout.write(self.style.SUCCESS("Authorization synchronized"))
