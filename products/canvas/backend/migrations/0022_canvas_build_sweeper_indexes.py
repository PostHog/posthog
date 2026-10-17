from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("canvas", "0021_mask_canvas_comment_activity"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="canvasbuild",
            index=models.Index(
                condition=models.Q(("status__in", ["queued", "building"])),
                fields=["status", "enqueued_at"],
                name="canvas_build_active_enqueued",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="canvasbuild",
            index=models.Index(
                condition=models.Q(("status__in", ["queued", "building"])),
                fields=["status", "lease_expires_at"],
                name="canvas_build_active_lease",
            ),
        ),
    ]
