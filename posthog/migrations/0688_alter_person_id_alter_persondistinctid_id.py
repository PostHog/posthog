# Generated by Django 4.2.18 on 2025-03-14 07:55
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0687_remove_taxonomy_team_only_constraints"),
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

                -- Add foreign key constraints back safely (with NOT VALID to avoid locking)
                ALTER TABLE "posthog_cohortpeople" ADD CONSTRAINT "posthog_cohortpeople_person_id_33da7d3f_fk"
                    FOREIGN KEY ("person_id") REFERENCES "posthog_person" ("id") NOT VALID;

                ALTER TABLE "posthog_featureflaghashkeyoverride" ADD CONSTRAINT "posthog_featureflaghashkeyoverride_person_id_7e517f7c_fk"
                    FOREIGN KEY ("person_id") REFERENCES "posthog_person" ("id") NOT VALID;

                ALTER TABLE "posthog_persondistinctid" ADD CONSTRAINT "posthog_persondistinctid_person_id_5d655bba_fk"
                    FOREIGN KEY ("person_id") REFERENCES "posthog_person" ("id") NOT VALID;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Validate constraints separately (runs without locking)
        migrations.RunSQL(
            sql="""
                ALTER TABLE "posthog_cohortpeople" VALIDATE CONSTRAINT "posthog_cohortpeople_person_id_33da7d3f_fk";
                ALTER TABLE "posthog_featureflaghashkeyoverride" VALIDATE CONSTRAINT "posthog_featureflaghashkeyoverride_person_id_7e517f7c_fk";
                ALTER TABLE "posthog_persondistinctid" VALIDATE CONSTRAINT "posthog_persondistinctid_person_id_5d655bba_fk";
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
