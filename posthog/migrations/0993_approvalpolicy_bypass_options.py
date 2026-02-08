from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0992_drop_approvalpolicy_bypass_roles_column"),
        ("ee", "0025_role_members"),
    ]

    operations = [
        migrations.AddField(
            model_name="approvalpolicy",
            name="bypass_org_membership_levels",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="approvalpolicy",
            name="bypass_roles",
            field=models.ManyToManyField(blank=True, related_name="bypass_policies", to="ee.role"),
        ),
    ]
