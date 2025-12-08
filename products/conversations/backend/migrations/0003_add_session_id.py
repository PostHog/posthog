# Generated migration for adding widget_session_id field to Ticket model

import uuid

from django.db import migrations, models


def generate_widget_session_ids(apps, schema_editor):
    """Populate widget_session_id for existing tickets with random UUIDs."""
    Ticket = apps.get_model("conversations", "Ticket")
    for ticket in Ticket.objects.filter(widget_session_id=""):
        ticket.widget_session_id = str(uuid.uuid4())
        ticket.save(update_fields=["widget_session_id"])


def reverse_generate_widget_session_ids(apps, schema_editor):
    """No-op reverse migration."""
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0002_rename_conversatio_team_id_8b1027_idx_posthog_con_team_id_0d4eff_idx_and_more"),
    ]

    operations = [
        # Add widget_session_id field with empty default (will be populated)
        migrations.AddField(
            model_name="ticket",
            name="widget_session_id",
            field=models.CharField(db_index=True, default="", max_length=64),
            preserve_default=False,
        ),
        # Populate existing tickets with random widget_session_ids
        migrations.RunPython(generate_widget_session_ids, reverse_generate_widget_session_ids),
        # Add index for (team, widget_session_id) queries
        migrations.AddIndex(
            model_name="ticket",
            index=models.Index(fields=["team", "widget_session_id"], name="posthog_con_team_id_wdgt_ss_idx"),
        ),
    ]
