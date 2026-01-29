from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0989_add_tags_to_hogflow_template"),
        ("ee", "0025_role_members"),
    ]

    operations = [
        migrations.AddField(
            model_name="approvalpolicy",
            name="bypass_org_membership_levels",
            field=models.JSONField(default=list),
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="approvalpolicy",
                    name="bypass_roles",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        -- migration-analyzer: safe reason=Feature not yet deployed, bypass_roles column has no production data
                        ALTER TABLE posthog_approvalpolicy DROP COLUMN IF EXISTS bypass_roles;
                    """,
                    reverse_sql="ALTER TABLE posthog_approvalpolicy ADD COLUMN bypass_roles jsonb NOT NULL DEFAULT '[]'::jsonb;",
                ),
            ],
        ),
        migrations.AddField(
            model_name="approvalpolicy",
            name="bypass_roles",
            field=models.ManyToManyField(blank=True, related_name="bypass_policies", to="ee.role"),
        ),
    ]
