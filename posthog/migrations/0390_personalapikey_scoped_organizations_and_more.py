# Generated by Django 4.1.13 on 2024-02-13 10:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0389_personalapikey_scopes"),
    ]

    operations = [
        migrations.AddField(
            model_name="personalapikey",
            name="scoped_organizations",
            field=models.CharField(blank=True, max_length=1000, null=True),
        ),
        migrations.AddField(
            model_name="personalapikey",
            name="scoped_teams",
            field=models.CharField(blank=True, max_length=1000, null=True),
        ),
    ]
