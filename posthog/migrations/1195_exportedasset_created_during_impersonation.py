from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1194_project_updated_at")]

    operations = [
        migrations.AddField(
            model_name="exportedasset",
            name="created_during_impersonation",
            field=models.BooleanField(default=False, null=True),
        ),
    ]
