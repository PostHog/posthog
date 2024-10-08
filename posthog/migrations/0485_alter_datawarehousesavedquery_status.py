# Generated by Django 4.2.15 on 2024-10-04 15:59

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0484_productintent"),
    ]

    operations = [
        migrations.AlterField(
            model_name="datawarehousesavedquery",
            name="status",
            field=models.CharField(
                choices=[
                    ("Cancelled", "Cancelled"),
                    ("Modified", "Modified"),
                    ("Completed", "Completed"),
                    ("Failed", "Failed"),
                    ("Running", "Running"),
                ],
                help_text="The status of when this SavedQuery last ran.",
                max_length=64,
                null=True,
            ),
        ),
    ]
