# Generated by Django 3.2.16 on 2023-02-16 11:47

import django.db.models.deletion
from django.db import migrations, models

# The previous migration attempted to add a constraint to the personoverride
# table. We want to remove that constraint, as the ForeignKey replaces this.
DROP_FUNCTION_FOR_CONSTRAINT_SQL = "DROP FUNCTION is_override_person_not_used_as_old_person"


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0300_add_constraints_to_person_override"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="personoverride",
            name="old_person_id_is_not_override_person_id",
        ),
        migrations.RunSQL(DROP_FUNCTION_FOR_CONSTRAINT_SQL),
        migrations.AddConstraint(
            model_name="person",
            constraint=models.UniqueConstraint(fields=("uuid",), name="unique uuid for person"),
        ),
        migrations.RemoveField(
            model_name="personoverride",
            name="override_person_id",
        ),
        migrations.AddField(
            model_name="personoverride",
            name="override_person",
            field=models.ForeignKey(
                default=0, on_delete=django.db.models.deletion.DO_NOTHING, to="posthog.person", to_field="uuid"
            ),
            preserve_default=False,
        ),
    ]
