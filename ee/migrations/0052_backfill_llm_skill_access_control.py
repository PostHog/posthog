from django.db import migrations

CHUNK_SIZE = 200


def backfill_llm_skill_access_control(apps, schema_editor):
    # llm_skill used to inherit its access level from llm_analytics (RESOURCE_INHERITANCE_MAP); now
    # that it's an independent resource, mirror every resource-wide llm_analytics grant onto a
    # matching llm_skill row so existing permissions keep working instead of silently falling back
    # to the default access level (editor, for everyone).
    #
    # Only resource-wide (resource_id=None) rows are in scope: RESOURCE_INHERITANCE_MAP only ever
    # backs the resource-level fallback (_access_controls_filters_for_resource hardcodes
    # resource_id=None) - object-level checks never consult it and always query the child resource
    # directly (see has_access_levels_for_resource in user_access_control.py). A resource_id-scoped
    # llm_analytics row is therefore a per-object grant on one of its OTHER children (dataset,
    # evaluation, tagger, llm_provider_key, llm_prompt - each queried under its own resource string)
    # and was never part of llm_skill's access resolution, so it's excluded here.
    #
    # llm_skill is also the scope_object for review_hog's config viewsets (blind spots, perspectives,
    # validators), which reused it rather than getting their own resource - so this also covers teams
    # that use those without ever touching Skills.
    AccessControl = apps.get_model("ee", "AccessControl")

    for row in AccessControl.objects.filter(resource="llm_analytics", resource_id__isnull=True).iterator(
        chunk_size=CHUNK_SIZE
    ):
        AccessControl.objects.get_or_create(
            resource="llm_skill",
            resource_id=None,
            team_id=row.team_id,
            organization_member_id=row.organization_member_id,
            role_id=row.role_id,
            defaults={"access_level": row.access_level, "created_by_id": row.created_by_id},
        )


def reverse_func(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("ee", "0051_backfill_ai_observability_clusters_access_control"),
    ]

    operations = [
        migrations.RunPython(backfill_llm_skill_access_control, reverse_func),
    ]
