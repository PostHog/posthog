from django.db import migrations


def replace_person_with_person_display_name(apps, schema_editor):
    Team = apps.get_model("posthog", "Team")
    for team in Team.objects.filter(live_events_columns__contains=["person"]):
        changed = False
        new_columns = []
        for col in team.live_events_columns:
            if col == "person":
                new_columns.append("person_display_name -- Person")
                changed = True
            else:
                new_columns.append(col)
        if changed:
            team.live_events_columns = new_columns
            team.save(update_fields=["live_events_columns"])


class Migration(migrations.Migration):
    dependencies = [("posthog", "0718_eventingestionrestrictionconfig")]

    operations = [
        migrations.RunPython(replace_person_with_person_display_name, reverse_code=migrations.RunPython.noop),
    ]
