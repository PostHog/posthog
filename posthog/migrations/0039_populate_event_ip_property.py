from django.db import migrations

def migrate_event_ip_to_property(apps, schema_editor):
    Event = apps.get_model('posthog', 'Event')
    events = Event.objects.all()

    for event in events:
        if event.ip:
            event.properties["$ip"] = event.ip
            event.save()

def rollback(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('posthog', '0038_migrate_actions_to_precalculate_events'),
    ]

    operations = [
        migrations.RunPython(migrate_event_ip_to_property, rollback),
    ]