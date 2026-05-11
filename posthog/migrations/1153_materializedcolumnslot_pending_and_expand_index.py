from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1152_fix_device_bucketing_persist_across_auth")]

    # Bundles three pre-shipping changes for MaterializedColumnSlot:
    # 1) slot_index becomes nullable + range expands to 0–99 + uniqueness becomes partial
    #    so multiple PENDING slots per team can coexist with no slot_index assigned.
    # 2) Add compaction_target_slot_index with its own partial unique constraint.
    # 3) Drop property_type from Django state only — every dmat column is `Nullable(String)`;
    #    HogQL casts at read using prop_def.property_type instead. The DB column is left in
    #    place per safe-django-migrations.md (multi-phase column drop). A future migration
    #    can drop the column once all running code no longer references it.
    #
    # Companion migrations:
    # - 1154_drop_property_type_not_null: DROP NOT NULL on the legacy `property_type`
    #   column so new code (which no longer sends it in INSERTs) doesn't violate the
    #   constraint. Split out of this migration because mixing RunSQL DDL with Django
    #   schema ops violates POSTHOG_POLICIES (RunSQL DDL and Django schema operations
    #   should be in separate migrations).
    # - 1155_*_concurrent_index: AddIndexConcurrently for `(team, slot_index)`. Split
    #   out because mixing CONCURRENTLY with regular DDL also violates POSTHOG_POLICIES.
    #
    # Multi-phase rename of `backfill_temporal_workflow_id` → `backfill_temporal_run_id`:
    #   Phase 1 (this migration): add the new column, drop the old column's index, and remove the
    #   old field from Django state (column kept physically — Django no longer reads/writes it).
    #   Phase 2 (1156_*_concurrent): add the index on the new column via AddIndexConcurrently.
    #   Phase 3 (future migration): DROP COLUMN backfill_temporal_workflow_id once this PR has
    #   propagated through a full deployment cycle.
    # dmat hasn't shipped yet so there's no in-flight data to copy between the old and new
    # columns. We avoid `RenameField` because the migration risk analyzer hard-blocks it
    # (score 4 BLOCKED, no override), while AddField + state-only RemoveField is Safe (score 1).

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
        # Drop property_type from Django state only — column stays in DB so old code that
        # still references it during the deployment cycle keeps working. The companion
        # migration 1154_drop_property_type_not_null then removes the NOT NULL constraint
        # so new code's INSERTs (which no longer include `property_type`) are accepted.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="materializedcolumnslot",
                    name="property_type",
                ),
            ],
            database_operations=[],
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
        # Re-add constraints in the new (property_type-free) shape.
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
        # Add the new column. Old column kept in DB until a follow-up migration drops it
        # (multi-phase column drop — RemoveField score-5 needs its own migration after deploy).
        migrations.AddField(
            model_name="materializedcolumnslot",
            name="backfill_temporal_run_id",
            field=models.CharField(max_length=400, null=True, blank=True),
        ),
        # Drop the index that covered the old column. No code reads or writes the old column
        # after this migration so there's no benefit to keeping its index around.
        migrations.RemoveIndex(
            model_name="materializedcolumnslot",
            name="posthog_mat_backfi_idx",
        ),
        # Remove the old field from Django state only. The physical column stays in Postgres
        # so a future migration can DROP it without a cross-deploy compat hazard.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="materializedcolumnslot",
                    name="backfill_temporal_workflow_id",
                ),
            ],
            database_operations=[],
        ),
    ]
