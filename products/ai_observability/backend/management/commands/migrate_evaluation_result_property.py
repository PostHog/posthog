from itertools import batched

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.event_definitions.backend.models.property_definition import PropertyDefinition


class Command(BaseCommand):
    help = (
        "Retype $ai_evaluation_result event metadata as String. Run after compatible query readers and "
        "property inference have deployed, before enabling numeric evaluations. Defaults to a dry run."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--batch-size", type=int, default=1000)

    def handle(self, *args: str, **options: object) -> None:
        batch_size = options["batch_size"]
        if not isinstance(batch_size, int) or batch_size < 1:
            raise CommandError("--batch-size must be positive")

        definitions = PropertyDefinition.objects.filter(
            name="$ai_evaluation_result", type=PropertyDefinition.Type.EVENT
        ).exclude(property_type="String", is_numerical=False)
        if not options["apply"]:
            self.stdout.write(f"Would update {definitions.count()} property definitions. Use --apply to migrate.")
            return

        updated = 0
        # Each batch commits independently so interrupted runs can resume without a long write transaction.
        ids = definitions.order_by().values_list("pk", flat=True).iterator(chunk_size=batch_size)
        for batch in batched(ids, batch_size, strict=False):
            updated += definitions.filter(pk__in=batch).update(property_type="String", is_numerical=False)
        self.stdout.write(f"Updated {updated} property definitions.")
