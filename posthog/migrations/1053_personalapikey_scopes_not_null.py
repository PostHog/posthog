import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1052_migrate_legacy_personal_api_key_scopes"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="personalapikey",
                    name="scopes",
                    field=django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=100), default=list, size=None
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""\
UPDATE posthog_personalapikey SET scopes = '{}' WHERE scopes IS NULL;
ALTER TABLE posthog_personalapikey ALTER COLUMN scopes SET NOT NULL; -- not-null-ignore: personalapikey is a small table, NULLs backfilled in 1052
""",
                    reverse_sql="ALTER TABLE posthog_personalapikey ALTER COLUMN scopes DROP NOT NULL;",
                ),
            ],
        ),
    ]
