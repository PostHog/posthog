# Generated by Django 3.0.11 on 2021-02-03 09:26

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0122_organization_setup_section_2_completed"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationinvite",
            name="first_name",
            field=models.CharField(blank=True, default="", max_length=30),
        ),
    ]
