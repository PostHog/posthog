from django.conf import settings
from django.db import migrations
from django.utils import timezone


def enable_allowlisted_teams(apps, schema_editor) -> None:
    Team = apps.get_model("posthog", "Team")
    AEOTeamConfig = apps.get_model("aeo", "AEOTeamConfig")
    wanted = set()
    for raw in getattr(settings, "AEO_CITATION_TEAM_IDS", []):
        try:
            wanted.add(int(str(raw).strip()))
        except ValueError:
            continue
    now = timezone.now()
    for team_id in Team.objects.filter(id__in=wanted).values_list("id", flat=True):
        AEOTeamConfig.objects.get_or_create(team_id=team_id, defaults={"enabled_at": now})


class Migration(migrations.Migration):
    dependencies = [
        ("aeo", "0019_aeo_team_config"),
    ]

    operations = [
        migrations.RunPython(enable_allowlisted_teams, reverse_code=migrations.RunPython.noop),
    ]
