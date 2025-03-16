# Generated by Django 4.2.18 on 2025-03-16 17:01
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0688_update_default_version"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                -- Drop existing foreign key constraints
                ALTER TABLE "posthog_cohortpeople" DROP CONSTRAINT IF EXISTS "posthog_cohortpeople_person_id_33da7d3f_fk";
                ALTER TABLE "posthog_featureflaghashkeyoverride" DROP CONSTRAINT IF EXISTS "posthog_featureflaghashkeyoverride_person_id_7e517f7c_fk";
                ALTER TABLE "posthog_persondistinctid" DROP CONSTRAINT IF EXISTS "posthog_persondistinctid_person_id_5d655bba_fk";

                -- Alter column types to bigint
                ALTER TABLE "posthog_person" ALTER COLUMN "id" TYPE bigint USING "id"::bigint;
                ALTER SEQUENCE IF EXISTS "posthog_person_id_seq" AS bigint;

                ALTER TABLE "posthog_cohortpeople" ALTER COLUMN "person_id" TYPE bigint USING "person_id"::bigint;
                ALTER TABLE "posthog_featureflaghashkeyoverride" ALTER COLUMN "person_id" TYPE bigint USING "person_id"::bigint;
                ALTER TABLE "posthog_persondistinctid" ALTER COLUMN "person_id" TYPE bigint USING "person_id"::bigint;

                ALTER TABLE "posthog_persondistinctid" ALTER COLUMN "id" TYPE bigint USING "id"::bigint;
                ALTER SEQUENCE IF EXISTS "posthog_persondistinctid_id_seq" AS bigint;

                -- Add constraints safely (with NOT VALID)
                ALTER TABLE "posthog_cohortpeople" ADD CONSTRAINT "posthog_cohortpeople_person_id_33da7d3f_fk"
                    FOREIGN KEY ("person_id") REFERENCES "posthog_person" ("id") NOT VALID;

                ALTER TABLE "posthog_featureflaghashkeyoverride" ADD CONSTRAINT "posthog_featureflaghashkeyoverride_person_id_7e517f7c_fk"
                    FOREIGN KEY ("person_id") REFERENCES "posthog_person" ("id") NOT VALID;

                ALTER TABLE "posthog_persondistinctid" ADD CONSTRAINT "posthog_persondistinctid_person_id_5d655bba_fk"
                    FOREIGN KEY ("person_id") REFERENCES "posthog_person" ("id") NOT VALID;
            """,
            reverse_sql=migrations.RunSQL.noop,
            state_operations=[
                migrations.AlterField(
                    model_name="person",
                    name="id",
                    field=models.BigAutoField(primary_key=True, serialize=False),
                ),
                migrations.AlterField(
                    model_name="persondistinctid",
                    name="id",
                    field=models.BigAutoField(primary_key=True, serialize=False),
                ),
                migrations.AlterField(
                    model_name="cohortpeople",
                    name="person",
                    field=models.ForeignKey(to="posthog.person", on_delete=models.CASCADE),
                ),
                migrations.AlterField(
                    model_name="featureflaghashkeyoverride",
                    name="person",
                    field=models.ForeignKey(to="posthog.person", on_delete=models.CASCADE),
                ),
                migrations.AlterField(
                    model_name="persondistinctid",
                    name="person",
                    field=models.ForeignKey(to="posthog.person", on_delete=models.CASCADE),
                ),
            ],
        ),
    ]
