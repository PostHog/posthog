# Generated by Django 4.2.18 on 2025-03-16 17:01
from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "0688_update_default_version"),
    ]

    operations = [
        # (1) Drop old constraints & convert columns to bigint
        migrations.RunSQL(
            sql="""
                ALTER TABLE "posthog_cohortpeople"
                    DROP CONSTRAINT IF EXISTS "posthog_cohortpeople_person_id_33da7d3f_fk";
                ALTER TABLE "posthog_featureflaghashkeyoverride"
                    DROP CONSTRAINT IF EXISTS "posthog_featureflaghashkeyoverride_person_id_7e517f7c_fk";
                ALTER TABLE "posthog_persondistinctid"
                    DROP CONSTRAINT IF EXISTS "posthog_persondistinctid_person_id_5d655bba_fk";

                ALTER TABLE "posthog_person"
                    ALTER COLUMN "id" TYPE bigint USING "id"::bigint;
                ALTER SEQUENCE IF EXISTS "posthog_person_id_seq" AS bigint;

                ALTER TABLE "posthog_cohortpeople"
                    ALTER COLUMN "person_id" TYPE bigint USING "person_id"::bigint;
                ALTER TABLE "posthog_featureflaghashkeyoverride"
                    ALTER COLUMN "person_id" TYPE bigint USING "person_id"::bigint;
                ALTER TABLE "posthog_persondistinctid"
                    ALTER COLUMN "person_id" TYPE bigint USING "person_id"::bigint;

                ALTER TABLE "posthog_persondistinctid"
                    ALTER COLUMN "id" TYPE bigint USING "id"::bigint;
                ALTER SEQUENCE IF EXISTS "posthog_persondistinctid_id_seq" AS bigint;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        # (2) Add constraints with NOT VALID + inline comment to ignore linter
        migrations.RunSQL(
            sql="""
                ALTER TABLE "posthog_cohortpeople"
                    ADD CONSTRAINT "posthog_cohortpeople_person_id_33da7d3f_fk"
                    FOREIGN KEY ("person_id") REFERENCES "posthog_person" ("id") NOT VALID; -- existing-table-constraint-ignore

                ALTER TABLE "posthog_featureflaghashkeyoverride"
                    ADD CONSTRAINT "posthog_featureflaghashkeyoverride_person_id_7e517f7c_fk"
                    FOREIGN KEY ("person_id") REFERENCES "posthog_person" ("id") NOT VALID; -- existing-table-constraint-ignore

                ALTER TABLE "posthog_persondistinctid"
                    ADD CONSTRAINT "posthog_persondistinctid_person_id_5d655bba_fk"
                    FOREIGN KEY ("person_id") REFERENCES "posthog_person" ("id") NOT VALID; -- existing-table-constraint-ignore
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        # (3) Validate constraints separately
        migrations.RunSQL(
            sql="""
                ALTER TABLE "posthog_cohortpeople"
                    VALIDATE CONSTRAINT "posthog_cohortpeople_person_id_33da7d3f_fk";

                ALTER TABLE "posthog_featureflaghashkeyoverride"
                    VALIDATE CONSTRAINT "posthog_featureflaghashkeyoverride_person_id_7e517f7c_fk";

                ALTER TABLE "posthog_persondistinctid"
                    VALIDATE CONSTRAINT "posthog_persondistinctid_person_id_5d655bba_fk";
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
