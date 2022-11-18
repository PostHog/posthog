# Generated by Django 3.2.16 on 2022-11-18 15:53

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0278_organization_customer_id"),
    ]

    operations = [
        migrations.AlterField(
            model_name="asyncdeletion",
            name="team",
            field=models.IntegerField(),
        ),
        migrations.RenameField(
            model_name="asyncdeletion",
            old_name="team",
            new_name="team_id",
        ),
    ]
