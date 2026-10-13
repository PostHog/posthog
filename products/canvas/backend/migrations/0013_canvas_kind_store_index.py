from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction, hence
    # atomic = False. SafeAddIndexConcurrently disables statement timeouts
    # and is idempotent under bin/migrate retries.
    atomic = False

    dependencies = [
        ("canvas", "0012_grid_canvas_foundation"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="canvas",
            index=models.Index(
                condition=models.Q(("kind", "freeform"), _negated=True),
                fields=["team", "kind"],
                name="canvas_kind_store",
            ),
        ),
    ]
