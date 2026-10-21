from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0020_untrack_dashboardtemplate_github_url"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE "posthog_dashboardtemplate" DROP COLUMN IF EXISTS "github_url"',
                    reverse_sql='ALTER TABLE "posthog_dashboardtemplate" ADD COLUMN "github_url" varchar(8201) NULL',
                ),
            ],
        ),
    ]
