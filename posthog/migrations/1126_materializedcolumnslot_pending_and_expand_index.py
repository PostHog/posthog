from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1125_scheduledchange_timezone")]

    operations = [
        # Drop the existing CheckConstraint and UniqueConstraint so we can recreate them
        # with the new shape (PENDING slots have no slot_index assigned yet, and the
        # valid range expands from 0-9 to 0-99 to accommodate the larger string column pool).
        migrations.RemoveConstraint(
            model_name="materializedcolumnslot",
            name="valid_slot_index",
        ),
        migrations.RemoveConstraint(
            model_name="materializedcolumnslot",
            name="unique_team_property_type_slot_index",
        ),
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
        migrations.AddConstraint(
            model_name="materializedcolumnslot",
            constraint=models.UniqueConstraint(
                fields=("team", "property_type", "slot_index"),
                name="unique_team_property_type_slot_index",
                condition=models.Q(slot_index__isnull=False),
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
                name="slot_index_required_when_assigned",
                condition=models.Q(state="PENDING") | models.Q(state="ERROR") | models.Q(slot_index__isnull=False),
            ),
        ),
    ]
