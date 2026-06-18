from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1110_sessionrecordingplaylistitem_playlist_index"),
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
        # with organization to form the link row. This is a state-only change
        # (the underlying table is OrganizationMembership, unaltered here).
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
    ]
