from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1126_materializedcolumnslot_pending_and_expand_index")]

    operations = [
        migrations.AddField(
            model_name="materializedcolumnslot",
            name="compaction_target_slot_index",
            field=models.PositiveSmallIntegerField(null=True, blank=True),
        ),
        migrations.AddConstraint(
            model_name="materializedcolumnslot",
            constraint=models.CheckConstraint(
                name="valid_compaction_target_slot_index",
                condition=models.Q(compaction_target_slot_index__isnull=True)
                | (models.Q(compaction_target_slot_index__gte=0) & models.Q(compaction_target_slot_index__lte=99)),
            ),
        ),
    ]
