import importlib

from django.db import migrations

# Web pods still on the release before 0096 could save judges without a key while it rolled out.
# Pinning again catches them before the active-key fallback goes. The pin only fills empty slots, so a second run is safe.
pin_judges_to_active_key = importlib.import_module(
    "products.ai_observability.backend.migrations.0096_pin_judges_to_active_key"
).pin_judges_to_active_key


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0096_pin_judges_to_active_key"),
    ]

    operations = [
        migrations.RunPython(pin_judges_to_active_key, migrations.RunPython.noop, elidable=True),
    ]
