# Generated by Django 3.0.3 on 2020-04-14 18:47

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models

def migrate_event_names_and_properties(apps, schema_editor):
    Team = apps.get_model('posthog', 'Team')
    Event = apps.get_model('posthog', 'Event')
    class JsonKeys(models.Func):
        function = 'jsonb_object_keys'

    for team in Team.objects.all():
        events = Event.objects.filter(team=team)
        keys = events\
            .annotate(keys=JsonKeys('properties'))\
            .distinct('keys')\
            .order_by('keys')\
            .values_list('keys', flat=True)
        names = events\
            .distinct('event')\
            .values_list('event', flat=True)
        team.event_keys = [key for key in keys]
        team.event_names = [name for name in names]
        team.save()

def noop(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('posthog', '0045_add_timestamp_index'),
    ]

    operations = [
        migrations.AddField(
            model_name='team',
            name='event_names',
            field=django.contrib.postgres.fields.jsonb.JSONField(default=list),
        ),
        migrations.AddField(
            model_name='team',
            name='event_properties',
            field=django.contrib.postgres.fields.jsonb.JSONField(default=list),
        ),

        migrations.RunPython(migrate_event_names_and_properties, noop)
    ]
