# Generated by Django 3.2.16 on 2023-02-02 14:32

import django.db.models.expressions
from django.db import migrations, models

# NOTE: I've moved these here to make sure that the migration is self-contained
# such that the state of the database is predictable.
#
# This function checks two things:
# 1. A new override_person_id must not match an existing old_person_id
# 2. A new old_person_id must not match an existing override_person_id
CREATE_FUNCTION_FOR_CONSTRAINT_SQL = f"""
CREATE OR REPLACE FUNCTION is_override_person_not_used_as_old_person(team_id bigint, override_person_id uuid, old_person_id uuid)
RETURNS BOOLEAN AS $$
  SELECT NOT EXISTS (
    SELECT 1
      FROM "posthog_personoverride"
      WHERE team_id = $1
      AND override_person_id = $3
    ) AND NOT EXISTS (
        SELECT 1
      FROM "posthog_personoverride"
      WHERE team_id = $1
      AND old_person_id = $2
    );
$$ LANGUAGE SQL;
"""

DROP_FUNCTION_FOR_CONSTRAINT_SQL = "DROP FUNCTION is_override_person_not_used_as_old_person"


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0299_set_templates_global"),
    ]

    operations = [
        migrations.RunSQL(
            CREATE_FUNCTION_FOR_CONSTRAINT_SQL,
            DROP_FUNCTION_FOR_CONSTRAINT_SQL,
        ),
        migrations.AddConstraint(
            model_name="personoverride",
            constraint=models.CheckConstraint(
                check=models.Q(
                    ("old_person_id__exact", django.db.models.expressions.F("override_person_id")), _negated=True
                ),
                name="old_person_id_different_from_override_person_id",
            ),
        ),
        migrations.AddConstraint(
            model_name="personoverride",
            constraint=models.CheckConstraint(
                check=models.Q(
                    django.db.models.expressions.Func(
                        django.db.models.expressions.F("team_id"),
                        django.db.models.expressions.F("override_person_id"),
                        django.db.models.expressions.F("old_person_id"),
                        function="is_override_person_not_used_as_old_person",
                        output_field=models.BooleanField(),
                    )
                ),
                name="old_person_id_is_not_override_person_id",
            ),
        ),
    ]
