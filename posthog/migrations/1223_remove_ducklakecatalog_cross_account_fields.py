from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1222_alter_integration_kind_google_analytics"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="ducklakecatalog",
                    name="cross_account_external_id",
                ),
                migrations.RemoveField(
                    model_name="ducklakecatalog",
                    name="cross_account_role_arn",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                    ALTER TABLE posthog_ducklakecatalog
                        ALTER COLUMN cross_account_external_id DROP NOT NULL,
                        ALTER COLUMN cross_account_role_arn DROP NOT NULL;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
