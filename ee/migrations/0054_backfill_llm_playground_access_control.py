from django.db import migrations

CHUNK_SIZE = 200


def backfill_llm_playground_access_control(apps, schema_editor):
    # The playground scene used to be gated on llm_analytics; now that it's an independent resource,
    # mirror every resource-wide llm_analytics grant onto a matching playground row so existing
    # permissions keep working instead of silently defaulting to editor. Rows with a resource_id are
    # per-object grants on other llm_analytics sub-resources (datasets, evaluations, ...) and aren't
    # playground-related, so they're excluded.
    # Reads the same resource-wide llm_analytics rows as ee/migrations/0053, so this is similarly near-instant.
    #
    # Levels can't be copied verbatim: llm_playground only offers "none" and "editor", so a viewer or
    # manager grant is collapsed to "editor". That preserves what these users could already do — before
    # this resource existed, any non-none llm_analytics level let them through the shared scene gate and
    # the run endpoint enforced nothing. Writing a "viewer" row here would also land a level outside the
    # resource's ladder, which the runtime access checks index into.
    AccessControl = apps.get_model("ee", "AccessControl")

    for row in AccessControl.objects.filter(resource="llm_analytics", resource_id__isnull=True).iterator(
        chunk_size=CHUNK_SIZE
    ):
        access_level = "none" if row.access_level == "none" else "editor"
        AccessControl.objects.get_or_create(
            resource="llm_playground",
            resource_id=None,
            team_id=row.team_id,
            organization_member_id=row.organization_member_id,
            role_id=row.role_id,
            defaults={"access_level": access_level, "created_by_id": row.created_by_id},
        )


def reverse_func(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("ee", "0053_backfill_tagger_access_control"),
    ]

    operations = [
        migrations.RunPython(backfill_llm_playground_access_control, reverse_func),
    ]
