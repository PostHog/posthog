# Generated by Django 4.2.11 on 2024-05-23 18:05

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0417_remove_organizationmembership_only_one_owner_per_organization"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationinvite",
            name="level",
            field=models.PositiveSmallIntegerField(
                choices=[(1, "member"), (8, "administrator"), (15, "owner")], default=1
            ),
        ),
    ]
