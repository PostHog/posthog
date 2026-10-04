from django.db import migrations
from django.db.models import Count


def clear_duplicate_default_channels(apps, schema_editor):
    # 0073 cannot build the unique index while a team has more than one default. Keep the
    # verified channel first, then the oldest one, which is the same order the disconnect
    # path uses to pick a replacement default.
    EmailChannel = apps.get_model("conversations", "EmailChannel")
    defaults = EmailChannel.objects.using(schema_editor.connection.alias).filter(is_default=True)
    team_ids = defaults.values("team_id").annotate(n=Count("id")).filter(n__gt=1).values_list("team_id", flat=True)
    for team_id in team_ids:
        keep = defaults.filter(team_id=team_id).order_by("-domain_verified", "created_at").first()
        if keep is not None:
            defaults.filter(team_id=team_id).exclude(id=keep.id).update(is_default=False)


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0071_emailchannel_trusted_relay_sender"),
    ]

    operations = [
        migrations.RunPython(clear_duplicate_default_channels, migrations.RunPython.noop),
    ]
