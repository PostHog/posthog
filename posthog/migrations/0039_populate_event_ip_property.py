from django.db import migrations

def migrate_event_ip_to_property(apps, schema_editor):
    Event = apps.get_model('posthog' 'Event')
    chunk = []
    
    # Use iterator to save memory
    for i, event in enumerate(Event.objects.only('properties', 'ip').iterator(chunk_size=10000)):
        if event.ip:
            event.properties['$ip'] = event.ip
            chunk.append(event)
        # Every 10000 events run bulk_update
        if i % 10000 == 0 and chunk:
            Event.objects.bulk_update(chunk, ['properties'])
            chunk = []
    if chunk:
        Event.objects.bulk_update(chunk, ['properties'])

def rollback(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('posthog', '0038_migrate_actions_to_precalculate_events'),
    ]

    operations = [
        migrations.RunPython(migrate_event_ip_to_property, rollback),
    ]