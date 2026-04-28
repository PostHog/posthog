from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1127_materializedcolumnslot_compaction_target")]

    operations = [
        # Defense-in-depth: the assignment planner already prevents two slots in one team from
        # claiming the same compaction_target_slot_index, but a partial unique index protects
        # against hand-edits, manual recovery scripts, and future planner regressions. Without
        # this, two slots in one team could end up dual-writing to the same target column and
        # corrupting each other's values during compaction.
        migrations.AddConstraint(
            model_name="materializedcolumnslot",
            constraint=models.UniqueConstraint(
                fields=("team", "property_type", "compaction_target_slot_index"),
                name="unique_team_property_type_compaction_target",
                condition=models.Q(compaction_target_slot_index__isnull=False),
            ),
        ),
    ]
