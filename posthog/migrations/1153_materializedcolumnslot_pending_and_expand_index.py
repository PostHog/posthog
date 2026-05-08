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
    # Note: the legacy `backfill_temporal_workflow_id` column is renamed in Python to
    # `backfill_temporal_run_id` via `db_column=` on the model — the physical column keeps
    # its old name, no RenameField needed (renames break old code mid-deployment).

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
        # State-only updates for the `backfill_temporal_workflow_id` → `backfill_temporal_run_id`
        # rename. The DB column and its index don't move — `db_column=` on the model attribute
        # preserves the existing column name. Renaming columns in prod is unsafe per
        # safe-django-migrations.md, so we limit the change to Django's view of the model.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameField(
                    model_name="materializedcolumnslot",
                    old_name="backfill_temporal_workflow_id",
                    new_name="backfill_temporal_run_id",
                ),
                # The model's `Index` keeps its existing name `posthog_mat_backfi_idx` and
                # references the renamed Python field; this just refreshes Django's view.
                migrations.RemoveIndex(
                    model_name="materializedcolumnslot",
                    name="posthog_mat_backfi_idx",
                ),
                migrations.AddIndex(
                    model_name="materializedcolumnslot",
                    index=models.Index(fields=["backfill_temporal_run_id"], name="posthog_mat_backfi_idx"),
                ),
                migrations.AlterField(
                    model_name="materializedcolumnslot",
                    name="backfill_temporal_run_id",
                    field=models.CharField(
                        blank=True, db_column="backfill_temporal_workflow_id", max_length=400, null=True
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
