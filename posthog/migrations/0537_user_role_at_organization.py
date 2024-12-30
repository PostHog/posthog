# Generated by Django 4.2.15 on 2024-12-30 17:47

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0536_alertconfiguration_skip_weekend"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="role_at_organization",
            field=models.CharField(
                blank=True,
                choices=[
                    ("engineering", "Engineering"),
                    ("data", "Data"),
                    ("product", "Product Management"),
                    ("founder", "Founder"),
                    ("leadership", "Leadership"),
                    ("marketing", "Marketing"),
                    ("sales", "Sales / Success"),
                    ("other", "Other"),
                ],
                max_length=64,
                null=True,
            ),
        ),
    ]
