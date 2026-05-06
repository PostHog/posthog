from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1148_backfill_encrypted_payloads_invariant")]

    # Bundles four pre-shipping changes for MaterializedColumnSlot:
    # 1) slot_index becomes nullable + range expands to 0–99 + uniqueness becomes partial
    #    so multiple PENDING slots per team can coexist with no slot_index assigned.
    # 2) Add compaction_target_slot_index with its own partial unique constraint.
    # 3) Drop property_type — every dmat column is `Nullable(String)`; HogQL casts at read
    #    using prop_def.property_type instead. Constraints collapse to (team, slot_index).
    # 4) Rename backfill_temporal_workflow_id → backfill_temporal_run_id (the schedule
    #    reuses one workflow_id, so the column always stored a run_id).

    operations = [
        migrations.RemoveConstraint(
            model_name="materializedcolumnslot",
            name="valid_slot_index",
        ),
        migrations.RemoveConstraint(
            model_name="materializedcolumnslot",
            name="unique_team_property_type_slot_index",
        ),
        migrations.RemoveIndex(
            model_name="materializedcolumnslot",
            name="posthog_mat_team_ty_idx",
        ),
        migrations.RemoveField(
            model_name="materializedcolumnslot",
            name="property_type",
        ),
        # Slot index becomes nullable for PENDING and ranges 0–99.
        migrations.AlterField(
            model_name="materializedcolumnslot",
            name="slot_index",
            field=models.PositiveSmallIntegerField(null=True, blank=True),
        ),
        migrations.AlterField(
            model_name="materializedcolumnslot",
            name="state",
            field=models.CharField(
                max_length=20,
                choices=[
                    ("PENDING", "Pending"),
                    ("BACKFILL", "Backfill"),
                    ("READY", "Ready"),
                    ("ERROR", "Error"),
                ],
                default="PENDING",
            ),
        ),
        # Compaction target field — set during repack, otherwise NULL.
        migrations.AddField(
            model_name="materializedcolumnslot",
            name="compaction_target_slot_index",
            field=models.PositiveSmallIntegerField(null=True, blank=True),
        ),
        # Re-add constraints and indexes in the new (property_type-free) shape.
        migrations.AddConstraint(
            model_name="materializedcolumnslot",
            constraint=models.UniqueConstraint(
                fields=("team", "slot_index"),
                name="unique_team_slot_index",
                condition=models.Q(slot_index__isnull=False),
            ),
        ),
        migrations.AddConstraint(
            model_name="materializedcolumnslot",
            constraint=models.UniqueConstraint(
                fields=("team", "compaction_target_slot_index"),
                name="unique_team_compaction_target",
                condition=models.Q(compaction_target_slot_index__isnull=False),
            ),
        ),
        migrations.AddConstraint(
            model_name="materializedcolumnslot",
            constraint=models.CheckConstraint(
                name="valid_slot_index",
                condition=models.Q(slot_index__isnull=True)
                | (models.Q(slot_index__gte=0) & models.Q(slot_index__lte=99)),
            ),
        ),
        migrations.AddConstraint(
            model_name="materializedcolumnslot",
            constraint=models.CheckConstraint(
                name="valid_compaction_target_slot_index",
                condition=models.Q(compaction_target_slot_index__isnull=True)
                | (models.Q(compaction_target_slot_index__gte=0) & models.Q(compaction_target_slot_index__lte=99)),
            ),
        ),
        migrations.AddConstraint(
            model_name="materializedcolumnslot",
            constraint=models.CheckConstraint(
                name="slot_index_required_when_assigned",
                condition=models.Q(state="PENDING") | models.Q(state="ERROR") | models.Q(slot_index__isnull=False),
            ),
        ),
        migrations.AddIndex(
            model_name="materializedcolumnslot",
            index=models.Index(fields=["team", "slot_index"], name="posthog_mat_team_sl_idx"),
        ),
        # Rename the legacy `backfill_temporal_workflow_id` column to `backfill_temporal_run_id`.
        # The old index is dropped first so the rename doesn't leave a stale index name behind.
        migrations.RemoveIndex(
            model_name="materializedcolumnslot",
            name="posthog_mat_backfi_idx",
        ),
        migrations.RenameField(
            model_name="materializedcolumnslot",
            old_name="backfill_temporal_workflow_id",
            new_name="backfill_temporal_run_id",
        ),
        migrations.AddIndex(
            model_name="materializedcolumnslot",
            index=models.Index(fields=["backfill_temporal_run_id"], name="posthog_mat_backfi_run_idx"),
        ),
    ]
