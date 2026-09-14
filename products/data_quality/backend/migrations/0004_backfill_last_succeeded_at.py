from django.db import migrations
from django.db.models import OuterRef, Subquery


def backfill_last_succeeded_at(apps, schema_editor):
    """Read the answer out of run history, which already holds it.

    Without this, every check that is already failing reads as "never passed" until its next
    success -- the one case where the field matters most. One UPDATE with a correlated subquery
    over the (quality_check, -created_at) index; checks are authored per table, so the outer table
    is small.
    """
    DataQualityCheck = apps.get_model("data_quality", "DataQualityCheck")
    DataQualityCheckRun = apps.get_model("data_quality", "DataQualityCheckRun")

    newest_pass = (
        DataQualityCheckRun.objects.filter(quality_check_id=OuterRef("pk"), status="passed")
        .order_by("-created_at")
        .values("created_at")[:1]
    )
    DataQualityCheck.objects.update(last_succeeded_at=Subquery(newest_pass))


class Migration(migrations.Migration):
    dependencies = [
        ("data_quality", "0003_dataqualitycheck_last_succeeded_at"),
    ]

    operations = [
        migrations.RunPython(backfill_last_succeeded_at, migrations.RunPython.noop, elidable=True),
    ]
