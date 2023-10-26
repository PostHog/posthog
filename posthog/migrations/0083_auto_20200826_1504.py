# Generated by Django 3.0.7 on 2020-08-26 15:04

import uuid

from django.db import migrations, models

from posthog.models.utils import UUIDT


def create_uuid(apps, schema_editor):
    Team = apps.get_model("posthog", "Team")
    for team in Team.objects.all():
        team.uuid = UUIDT()
        team.save()


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0082_personalapikey"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="ingested_event",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="team",
            name="uuid",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.RunPython(create_uuid, migrations.RunPython.noop, elidable=True),
        migrations.AlterField(
            model_name="team",
            name="uuid",
            field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False),
        ),
    ]
