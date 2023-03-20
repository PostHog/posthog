# Generated by Django 3.2.16 on 2023-03-14 11:26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0310_add_starter_dashboard_template"),
    ]

    operations = [
        migrations.AddField(
            # safe to ignore null locking this table it has fewer than 10 items on it
            model_name="dashboardtemplate",
            name="scope",
            field=models.CharField(
                choices=[("team", "Only team"), ("global", "Global")], max_length=24, null=True, blank=True
            ),
        ),
        migrations.RunSQL(
            # safe to ignore null locking this table it has fewer than 10 items on it
            sql="""
                UPDATE posthog_dashboardtemplate SET scope = 'global' WHERE team_id IS NULL -- not-null-ignore
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            # safe to ignore null locking this table it has fewer than 10 items on it
            sql="""
                UPDATE posthog_dashboardtemplate SET scope = 'team' WHERE team_id IS NOT NULL -- not-null-ignore
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
