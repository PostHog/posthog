# Generated by Django 3.2.16 on 2023-03-01 17:03

import django.contrib.postgres.constraints
import django.db.models.deletion
import django.db.models.expressions
from django.db import migrations, models

# The previous migration attempted to add a constraint to the personoverride
# table. We want to remove that constraint, as the ForeignKey replaces this.
# The function was never used, but to make migrations work we need these two
DROP_FUNCTION_FOR_CONSTRAINT_SQL = "DROP FUNCTION is_override_person_not_used_as_old_person"
CREATE_FUNCTION_FOR_CONSTRAINT_SQL = f"""
CREATE OR REPLACE FUNCTION is_override_person_not_used_as_old_person(team_id bigint, override_person_id uuid, old_person_id uuid)
RETURNS BOOLEAN AS $$
  SELECT false;
$$ LANGUAGE SQL;
"""

DROP_FUNCTION_FOR_CONSTRAINT_SQL = "DROP FUNCTION is_override_person_not_used_as_old_person"


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0307_pluginconfig_admin"),
    ]

    operations = [
        migrations.CreateModel(
            name="PersonOverrideMapping",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("uuid", models.UUIDField()),
                ("team_id", models.BigIntegerField()),
            ],
        ),
        migrations.RemoveConstraint(
            model_name="personoverride",
            name="unique override per old_person_id",
        ),
        migrations.RemoveConstraint(
            model_name="personoverride",
            name="old_person_id_is_not_override_person_id",
        ),
        migrations.RunSQL(DROP_FUNCTION_FOR_CONSTRAINT_SQL, CREATE_FUNCTION_FOR_CONSTRAINT_SQL),
        migrations.RemoveField(model_name="personoverride", name="old_person_id"),
        migrations.AddField(
            model_name="personoverride",
            name="old_person_id",
            field=models.ForeignKey(
                db_column="old_person_id",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="person_override_old",
                to="posthog.personoverridemapping",
            ),
        ),
        migrations.RemoveField(model_name="personoverride", name="override_person_id"),
        migrations.AddField(
            model_name="personoverride",
            name="override_person_id",
            field=models.ForeignKey(
                db_column="override_person_id",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="person_override_override",
                to="posthog.personoverridemapping",
            ),
        ),
        migrations.AddConstraint(
            model_name="personoverride",
            constraint=models.UniqueConstraint(
                fields=("team", "old_person_id"), name="unique override per old_person_id"
            ),
        ),
        # Provides operator classes for integers (gist_int4_ops)
        migrations.RunSQL("CREATE EXTENSION IF EXISTS btree_gist", "DROP EXTENSION btree_gist"),
        # Provides operator classes for integer arrays (gist__int_ops)
        migrations.RunSQL("CREATE EXTENSION IF EXISTS intarray", "DROP EXTENSION intarray"),
        migrations.RunSQL(
            """
            ALTER TABLE posthog_personoverride
            ADD CONSTRAINT exclude_override_person_id_from_being_old_person_id
            EXCLUDE USING gist((array[old_person_id, override_person_id]) WITH &&, override_person_id WITH <>)
            DEFERRABLE
            INITIALLY DEFERRED
            """,
            "ALTER TABLE posthog_personoverride DROP CONSTRAINT exclude_override_person_id_from_being_old_person_id",
        ),
        migrations.AddConstraint(
            model_name="personoverridemapping",
            constraint=models.UniqueConstraint(fields=("team_id", "uuid"), name="unique_uuid"),
        ),
    ]
