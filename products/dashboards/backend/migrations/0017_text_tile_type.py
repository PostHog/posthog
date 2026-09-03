from django.db import migrations, models


def classify_legacy_text_tiles(apps, schema_editor) -> None:
    Text = apps.get_model("dashboards", "Text")
    database = schema_editor.connection.alias
    Text.objects.using(database).filter(
        body__regex=r'^\s*<hr data-dashboard-separator-thickness="(thin|medium|thick)" />\s*$',
    ).update(tile_type="divider")


class Migration(migrations.Migration):
    dependencies = [("dashboards", "0016_dashboardsavedview")]

    operations = [
        migrations.AddField(
            model_name="text",
            name="tile_type",
            field=models.CharField(
                db_default="text",
                default="text",
                max_length=64,
            ),
        ),
        migrations.RunPython(classify_legacy_text_tiles, migrations.RunPython.noop),
    ]
