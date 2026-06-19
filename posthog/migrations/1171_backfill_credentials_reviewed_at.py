from django.db import migrations
from django.utils import timezone

BATCH_SIZE = 10_000


def backfill_credentials_reviewed_at(apps, schema_editor):
    User = apps.get_model("posthog", "User")
    now = timezone.now()

    queryset = User.objects.filter(credentials_reviewed_at__isnull=True).only("id")
    while True:
        ids = list(queryset.values_list("id", flat=True)[:BATCH_SIZE])
        if not ids:
            break
        User.objects.filter(id__in=ids).update(credentials_reviewed_at=now)


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1170_credentials_reviewed_at"),
    ]

    operations = [
        migrations.RunPython(backfill_credentials_reviewed_at, reverse_code=migrations.RunPython.noop),
    ]
