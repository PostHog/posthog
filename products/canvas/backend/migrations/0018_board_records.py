import django.db.models.deletion
from django.db import migrations, models

import posthog.uuidt


class Migration(migrations.Migration):
    dependencies = [
        ("canvas", "0017_canvas_board"),
        ("posthog", "1339_validate_taggeditem_project_fk"),
    ]

    operations = [
        migrations.AddField(
            model_name="canvasboard",
            name="records_seq",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="CanvasBoardRecord",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.uuidt.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("fragment", "Fragment"),
                            ("source", "Source"),
                            ("state", "State"),
                        ],
                        max_length=8,
                    ),
                ),
                ("key", models.CharField(max_length=128)),
                ("value", models.JSONField()),
                ("position", models.IntegerField(default=0)),
                ("seq", models.IntegerField()),
                (
                    "board",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="records",
                        to="canvas.canvasboard",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_canvas_board_record",
                "indexes": [
                    models.Index(
                        fields=["board", "kind", "position"],
                        name="canvas_board_record_order",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("board", "kind", "key"), name="canvas_board_record_key")
                ],
            },
        ),
    ]
