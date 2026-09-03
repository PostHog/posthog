from django.db import migrations


def classify_legacy_divider_tiles(apps, schema_editor) -> None:
    Text = apps.get_model("dashboards", "Text")
    Text.objects.using(schema_editor.connection.alias).filter(
        body__regex=r'^\s*<hr data-dashboard-separator-thickness="(thin|medium|thick)" />\s*$',
    ).update(tile_type="divider")


class Migration(migrations.Migration):
    dependencies = [("dashboards", "0017_text_tile_type")]

    operations = [migrations.RunPython(classify_legacy_divider_tiles, migrations.RunPython.noop)]
