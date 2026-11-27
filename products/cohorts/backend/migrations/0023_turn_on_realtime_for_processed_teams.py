from datetime import UTC, datetime

from django.conf import settings
from django.db import migrations
from django.db.models import Value
from django.db.models.functions import Coalesce

_MAX_RANGE_SPAN = 100_000


# A copy of `realtime_teams._team_in_allowlist`, so a later change to that module cannot change what
# this migration did.
def _team_in_allowlist(raw_allowlist: str, team_id: int) -> bool:
    raw_allowlist = raw_allowlist.strip()
    if raw_allowlist == "" or raw_allowlist.lower() == "all" or raw_allowlist == "*":
        return True
    if raw_allowlist.lower() == "none":
        return False
    for part in (segment.strip() for segment in raw_allowlist.split(",")):
        if not part:
            continue
        start_raw, is_range, end_raw = part.partition(":")
        try:
            start, end = (int(start_raw.strip()), int(end_raw.strip())) if is_range else (int(part), int(part))
        except ValueError:
            continue
        if start <= end <= start + _MAX_RANGE_SPAN - 1 and start <= team_id <= end:
            return True
    return False


def turn_on_processed_realtime_cohorts(apps, schema_editor):
    # The pipeline starts loading only cohorts that are on, so every cohort it loads today has to be on
    # before that release, deleted ones too so an undelete behaves as before. The finalizer stamps only for
    # a run created after realtime was turned on, so the creation time keeps runs in flight stamping.
    Cohort = apps.get_model("cohorts", "Cohort")
    RealtimeCohortTeamAccess = apps.get_model("cohorts", "RealtimeCohortTeamAccess")

    granted = set(RealtimeCohortTeamAccess.objects.exclude(level="off").values_list("team_id", flat=True))
    realtime = Cohort.objects.filter(cohort_type="realtime", realtime_enabled_at__isnull=True)
    team_ids = [
        team_id
        for team_id in realtime.values_list("team_id", flat=True).distinct()
        if team_id in granted or _team_in_allowlist(settings.REALTIME_COHORT_TEAM_ALLOWLIST, team_id)
    ]
    if team_ids:
        realtime.filter(team_id__in=team_ids).update(
            realtime_enabled_at=Coalesce("created_at", Value(datetime(2020, 1, 1, tzinfo=UTC)))
        )


class Migration(migrations.Migration):
    dependencies = [
        ("cohorts", "0022_cohort_realtime_enabled_at"),
    ]

    operations = [
        migrations.RunPython(turn_on_processed_realtime_cohorts, migrations.RunPython.noop),
    ]
