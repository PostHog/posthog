from django.core.management.base import BaseCommand

from products.authz.backend.bootstrap import bootstrap_openfga


class Command(BaseCommand):
    def handle(self, *args: object, **options: object) -> None:
        model_id = bootstrap_openfga()
        self.stdout.write(self.style.SUCCESS(f"Uploaded OpenFGA authorization model {model_id}"))
