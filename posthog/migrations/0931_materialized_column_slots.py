import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0930_user_shortcut_position"),
    ]

    operations = [
        migrations.CreateModel(
            name="MaterializedColumnSlot",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="materialized_column_slots",
                        related_query_name="materialized_column_slot",
                        to="posthog.team",
                    ),
                ),
                (
                    "property_definition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="materialized_column_slots",
                        related_query_name="materialized_column_slot",
                        to="posthog.propertydefinition",
                    ),
                ),
                (
                    "property_type",
                    models.CharField(
                        max_length=50,
                        choices=[
                            ("DateTime", "DateTime"),
                            ("String", "String"),
                            ("Numeric", "Numeric"),
                            ("Boolean", "Boolean"),
                            ("Duration", "Duration"),
                        ],
                    ),
                ),
                ("slot_index", models.PositiveSmallIntegerField()),
                (
                    "state",
                    models.CharField(
                        max_length=20,
                        choices=[
                            ("BACKFILL", "Backfill"),
                            ("READY", "Ready"),
                            ("ERROR", "Error"),
                        ],
                        default="BACKFILL",
                    ),
                ),
                ("backfill_temporal_workflow_id", models.CharField(max_length=400, null=True, blank=True)),
                ("error_message", models.TextField(null=True, blank=True)),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddConstraint(
            model_name="materializedcolumnslot",
            constraint=models.UniqueConstraint(
                fields=("team", "property_definition"),
                name="unique_team_property_definition",
            ),
        ),
        migrations.AddConstraint(
            model_name="materializedcolumnslot",
            constraint=models.UniqueConstraint(
                fields=("team", "property_type", "slot_index"),
                name="unique_team_property_type_slot_index",
            ),
        ),
        migrations.AddConstraint(
            model_name="materializedcolumnslot",
            constraint=models.CheckConstraint(
                name="valid_slot_index",
                check=models.Q(slot_index__gte=0) & models.Q(slot_index__lte=9),
            ),
        ),
        migrations.AddIndex(
            model_name="materializedcolumnslot",
            index=models.Index(fields=["team", "state"], name="posthog_mat_team_st_idx"),
        ),
        migrations.AddIndex(
            model_name="materializedcolumnslot",
            index=models.Index(
                fields=["team", "property_definition"],
                name="posthog_mat_team_pr_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="materializedcolumnslot",
            index=models.Index(
                fields=["team", "property_type", "slot_index"],
                name="posthog_mat_team_ty_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="materializedcolumnslot",
            index=models.Index(
                fields=["backfill_temporal_workflow_id"],
                name="posthog_mat_backfi_idx",
            ),
        ),
    ]
