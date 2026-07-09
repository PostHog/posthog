from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("annotations", "0003_annotation_hidden_in_user_interface"),
    ]

    operations = [
        migrations.AlterField(
            model_name="annotation",
            name="scope",
            field=models.CharField(
                choices=[
                    ("dashboard_item", "insight"),
                    ("dashboard", "dashboard"),
                    ("project", "project"),
                    ("organization", "organization"),
                    ("tag", "tag"),
                    ("recording", "recording"),
                ],
                default="dashboard_item",
                max_length=24,
            ),
        ),
    ]
