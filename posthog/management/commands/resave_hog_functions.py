from django.core.management.base import BaseCommand
from posthog.models import HogFunction


class Command(BaseCommand):
    help = "Re-enables HogFunctions by triggering a reload on the plugin server"

    def add_arguments(self, parser):
        parser.add_argument("--ids", nargs="+", type=str, help="List of HogFunction IDs to re-enable")

    def handle(self, *args, **options):
        if not options["ids"]:
            self.stdout.write(self.style.ERROR("Please provide HogFunction IDs"))
            return

        hog_function_ids = options["ids"]
        functions = HogFunction.objects.filter(id__in=hog_function_ids)
        count = 0

        for function in functions:
            function.save(update_fields=["updated_at"])  # Minimal save to trigger the signal
            count += 1
            self.stdout.write(f"Triggered reload for HogFunction {function.id}: {function.name}")

        self.stdout.write(self.style.SUCCESS(f"Successfully triggered reload for {count} HogFunctions"))
