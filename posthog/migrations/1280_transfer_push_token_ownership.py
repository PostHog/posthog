from django.db import migrations
from django.db.models import Count


def keep_latest_token_owner(apps, schema_editor):
    UserPushToken = apps.get_model("posthog", "UserPushToken")
    duplicate_tokens = UserPushToken.objects.values("token").annotate(owner_count=Count("id")).filter(owner_count__gt=1)
    for token in duplicate_tokens.iterator(chunk_size=1000):
        rows = UserPushToken.objects.filter(token=token["token"]).order_by("-last_seen_at", "-created_at")
        keep_id = rows.values_list("id", flat=True).first()
        rows.exclude(id=keep_id).delete()


class Migration(migrations.Migration):
    dependencies = [("posthog", "1279_drop_duckgresserverteam_table")]

    operations = [
        migrations.RunPython(keep_latest_token_owner, migrations.RunPython.noop),
    ]
