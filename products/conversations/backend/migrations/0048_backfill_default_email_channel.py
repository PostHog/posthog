from django.db import migrations


def backfill_default_channel(apps, schema_editor):
    # Give every team with existing channels a default, matching what selection did before this
    # field existed: prefer the oldest verified channel, else the oldest channel. Runs before the
    # partial unique constraint is added (0049), so setting one per team can't violate it.
    EmailChannel = apps.get_model("conversations", "EmailChannel")
    team_ids = EmailChannel.objects.values_list("team_id", flat=True).distinct()
    for team_id in team_ids:
        channels = list(EmailChannel.objects.filter(team_id=team_id).order_by("created_at"))
        default = next((c for c in channels if c.domain_verified), channels[0])
        default.is_default = True
        default.save(update_fields=["is_default"])


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0047_emailchannel_is_default"),
    ]

    operations = [
        migrations.RunPython(backfill_default_channel, migrations.RunPython.noop),
    ]
