from django.db import migrations


REKEY_PERSON_DISTINCT_ID_SQL = """
    BEGIN;
    DROP SEQUENCE posthog_persondistinctid_id_seq;
    ALTER TABLE posthog_persondistinctid DROP CONSTRAINT posthog_persondistinctid_pkey;
    ALTER TABLE posthog_persondistinctid ALTER COLUMN id SET DEFAULT 2147483647;
    ALTER TABLE posthog_persondistinctid ADD PRIMARY KEY (team_id, distinct_id);
    COMMIT;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0313_early_access_feature"),
    ]

    operations = [
        migrations.RunSQL(REKEY_PERSON_DISTINCT_ID_SQL, reverse_sql=migrations.RunSQL.noop),
    ]
