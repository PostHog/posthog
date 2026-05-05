from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1143_sharingconfiguration_notebook")]

    # Single in-flight migration that brings the MaterializedColumnSlot model fully in line
    # with the dynamic property materialization RFC. None of these changes have shipped, so
    # they're folded into one migration rather than three.
    #
    # 1) PENDING flow: slot_index is now nullable so a slot can sit in PENDING with no column
    #    assigned, and the assigned-range expands from 0–9 to 0–99 to match the larger string
    #    column pool. The slot_index uniqueness becomes partial (only enforced for rows with a
    #    non-null slot_index) so multiple PENDING slots can coexist.
    #
    # 2) compaction_target_slot_index: when a slot is being repacked into a smaller column
    #    index, ingestion dual-writes to both columns until the historical mutation completes
    #    and the workflow swaps `slot_index ← compaction_target_slot_index`. The partial
    #    unique constraint on (team, compaction_target_slot_index) prevents two slots in one
    #    team from claiming the same target column — defense-in-depth around a planner bug.
    #
    # 3) Drop `property_type` from the slot. Per the RFC every dmat column is `Nullable(String)`;
    #    HogQL applies the type wrapper at read time using `prop_def.property_type`, the same
    #    way it does for normal `mat_*` columns. Without `property_type` on the slot the
    #    constraints/indexes that were keyed on `(team, property_type, slot_index)` collapse
    #    to `(team, slot_index)` — per-team uniqueness is what protects against two slots in
    #    one team dual-writing to the same dmat column.

    operations = [
        # Drop everything keyed on the old shape first, so we can drop the property_type field cleanly.
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
    ]
