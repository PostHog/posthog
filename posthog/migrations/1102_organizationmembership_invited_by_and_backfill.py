from django.db import migrations, models
from django.utils import timezone


def backfill_welcome_screen_seen_at(apps, schema_editor):
    """Mark existing memberships as having already seen the welcome screen.

    Without this, every pre-existing invitee (anyone who's ever been invited to an org)
    would see the welcome dialog on the first page load after the feature ships.
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
        ("posthog", "1101_organizationmembership_welcome_screen_seen_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationmembership",
            name="invited_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="+",
                to="posthog.user",
            ),
        ),
        # OrganizationMembership now has two FKs to User (user + invited_by), so the
        # Organization.members M2M needs through_fields to disambiguate which one pairs
        # with organization to form the link row.
        migrations.AlterField(
            model_name="organization",
            name="members",
            field=models.ManyToManyField(
                related_name="organizations",
                related_query_name="organization",
                through="posthog.OrganizationMembership",
                through_fields=("organization", "user"),
                to="posthog.user",
            ),
        ),
        migrations.RunPython(backfill_welcome_screen_seen_at, reverse_backfill),
    ]
