from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0048_alter_externaldatasource_source_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldatasource",
            name="created_via",
            field=models.CharField(
                blank=True,
                choices=[("web", "web"), ("api", "api"), ("mcp", "mcp")],
                max_length=20,
                null=True,
            ),
        ),
    ]
