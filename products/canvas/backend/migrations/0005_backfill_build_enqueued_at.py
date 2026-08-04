from django.db import migrations, models


def backfill_enqueued_at(apps, schema_editor):
    CanvasBuild = apps.get_model("canvas", "CanvasBuild")
    CanvasBuild.objects.filter(enqueued_at__isnull=True).update(enqueued_at=models.F("created_at"))


class Migration(migrations.Migration):
    dependencies = [("canvas", "0004_build_enqueued_at")]

    operations = [migrations.RunPython(backfill_enqueued_at, migrations.RunPython.noop)]
