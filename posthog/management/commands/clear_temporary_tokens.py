from django.core.management.base import BaseCommand

from posthog.models import User

BATCH_SIZE = 5000


class Command(BaseCommand):
    help = "Clear temporary_token for all users (one-time cleanup after migrating to toolbar OAuth)"

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help="Rows per UPDATE batch")

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        total_updated = 0

        while True:
            ids = list(
                User.objects.filter(temporary_token__isnull=False)
                .exclude(temporary_token="")
                .values_list("id", flat=True)[:batch_size]
            )
            if not ids:
                break

            updated = User.objects.filter(id__in=ids).update(temporary_token=None)
            total_updated += updated
            self.stdout.write(f"  Cleared {updated} rows (total so far: {total_updated})")

        if total_updated == 0:
            self.stdout.write("No users with temporary tokens found.")
        else:
            self.stdout.write(self.style.SUCCESS(f"Done. Cleared temporary_token for {total_updated} user(s)."))
