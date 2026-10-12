from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0003_alter_approvalpolicy_organization_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="changerequest",
            name="owner_kind",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
