import django.utils.timezone
import django.db.models.deletion
from django.db import migrations, models

import posthog.uuidt


class Migration(migrations.Migration):
    dependencies = [
        ("canvas", "0021_mask_canvas_comment_activity"),
        ("posthog", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="CanvasDataCheck",
            fields=[
                (
                    "id",
                    models.UUIDField(default=posthog.uuidt.uuid7, editable=False, primary_key=True, serialize=False),
                ),
                ("status", models.CharField(max_length=16)),
                ("missing", models.JSONField(default=dict)),
                ("checked_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "canvas",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE, related_name="data_check", to="canvas.canvas"
                    ),
                ),
                (
                    "source_version",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="canvas.canvassourceversion",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_canvas_data_check",
            },
        ),
    ]
