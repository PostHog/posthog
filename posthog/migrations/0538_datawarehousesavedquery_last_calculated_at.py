# Generated by Django 4.2.15 on 2025-01-02 16:09

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0537_data_color_themes"),
    ]

    operations = [
        migrations.AddField(
            model_name="datawarehousesavedquery",
            name="last_calculated_at",
            field=models.DateTimeField(help_text="The timestamp of this SavedQuery's last calculation.", null=True),
        ),
    ]
