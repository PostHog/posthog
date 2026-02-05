from django.db import migrations


def remove_presorted_events_modifier(apps, schema_editor):
    Insight = apps.get_model("posthog", "Insight")

    # Find all insights that have the usePresortedEventsTable modifier
    # Check both query->modifiers and query->source->modifiers paths
    items_to_update = Insight.objects.raw("""
        SELECT * FROM posthog_dashboarditem
        WHERE query->'modifiers' ? 'usePresortedEventsTable'
           OR query->'source'->'modifiers' ? 'usePresortedEventsTable'
    """)

    batch_size = 1000
    batch = []

    for item in items_to_update:
        if not item.query:
            continue

        modified = False

        # Handle query->modifiers path
        if "modifiers" in item.query and isinstance(item.query["modifiers"], dict):
            if "usePresortedEventsTable" in item.query["modifiers"]:
                del item.query["modifiers"]["usePresortedEventsTable"]
                modified = True

        # Handle query->source->modifiers path
        if "source" in item.query and isinstance(item.query["source"], dict):
            if "modifiers" in item.query["source"] and isinstance(item.query["source"]["modifiers"], dict):
                if "usePresortedEventsTable" in item.query["source"]["modifiers"]:
                    del item.query["source"]["modifiers"]["usePresortedEventsTable"]
                    modified = True

        if modified:
            batch.append(item)

            if len(batch) >= batch_size:
                Insight.objects.bulk_update(batch, ["query"])
                batch = []

    if batch:
        Insight.objects.bulk_update(batch, ["query"])


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0998_team_proactive_tasks_enabled"),
    ]

    operations = [
        migrations.RunPython(
            remove_presorted_events_modifier,
            reverse_noop,
        ),
    ]
