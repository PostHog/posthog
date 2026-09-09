from django.db import migrations, models

import products.canvas.backend.models


class Migration(migrations.Migration):
    dependencies = [("canvas", "0018_sketchpad")]

    operations = [
        migrations.AddField(
            model_name="sketchpad",
            name="history_snapshot",
            field=models.JSONField(
                db_default={"schemaVersion": 1, "fragments": [], "state": {}},
                default=products.canvas.backend.models.empty_sketchpad_snapshot,
            ),
        ),
        migrations.AddField(
            model_name="sketchpad",
            name="history_start_seq",
            field=models.IntegerField(db_default=0, default=0),
        ),
    ]
