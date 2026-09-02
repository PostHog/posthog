import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("canvas", "0005_backfill_build_enqueued_at")]

    operations = [
        migrations.AlterField(
            model_name="canvasbuild",
            name="enqueued_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        )
    ]
