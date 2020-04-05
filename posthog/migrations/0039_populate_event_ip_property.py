from django.db import migrations

def migrate_event_ip_to_property(apps, schema_editor):
    Event = apps.get_model('posthog', 'Event')
    batch_size = 10000
    events_count = Event.objects.count()
    all_events = Event.objects.all()
    for i in range(0, events_count, batch_size):
        events = all_events[i:i+batch_size]
        for event in events:
            if event.ip:
                event.properties["$ip"] = event.ip
        Event.objects.bulk_update(events, ['properties'])

def rollback(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('posthog', '0038_migrate_actions_to_precalculate_events'),
    ]

    operations = [
        migrations.RunPython(migrate_event_ip_to_property, rollback),
    ]