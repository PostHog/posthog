from django.db import migrations
from django.utils import timezone


def backfill_welcome_screen_seen_at(apps, schema_editor):
    """Mark existing memberships as having already seen the welcome screen.

    Without this, every pre-existing invitee (anyone who's ever been invited to an org)
    would see the welcome dialog on the first page load after the feature ships.

    Uses a single UPDATE, which is fine at the current member-row scale. If this ever
    becomes expensive on a large deployment the caller can batch via `.iterator()` +
    `.bulk_update()` instead.
    """
    OrganizationMembership = apps.get_model("posthog", "OrganizationMembership")
    OrganizationMembership.objects.filter(welcome_screen_seen_at__isnull=True).update(
        welcome_screen_seen_at=timezone.now()
    )


def reverse_backfill(apps, schema_editor):
    # Intentional no-op — we can't tell which rows were backfilled vs. set by actual dismissals.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1103_organizationmembership_invited_by_and_backfill"),
    ]

    operations = [
        migrations.RunPython(backfill_welcome_screen_seen_at, reverse_backfill),
    ]
