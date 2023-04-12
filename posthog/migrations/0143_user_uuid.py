# Generated by Django 3.0.11 on 2021-04-05 19:23

from django.db import migrations, models

import posthog.models.utils


def create_user_uuid(apps, schema_editor):
    User = apps.get_model("posthog", "User")
    for user in User.objects.all():
        user.uuid = posthog.models.utils.UUIDT()
        user.save()


def backwards(app, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0142_fix_team_data_attributes_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="uuid",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.RunPython(create_user_uuid, backwards, elidable=True),
        migrations.AlterField(
            model_name="user",
            name="uuid",
            field=models.UUIDField(default=posthog.models.utils.UUIDT, unique=True, editable=False),
        ),
    ]
