from django.db import migrations

VALID_COHORT_OPERATORS = {None, "in", "not_in"}


def normalize_cohort_flag_operators(apps, schema_editor):
    """
    Fix feature flag release conditions that target a cohort with an operator other
    than `in`/`not_in`. Cohort membership is binary, so operators like `is_not`
    (produced by older AI-assisted edits while the UI hid the `not_in` option) hit
    the Rust engine's catch-all arm and evaluate to false for everyone — silently
    disabling the condition. `is_not` clearly meant "not in"; anything else collapses
    to plain membership.
    """
    FeatureFlag = apps.get_model("posthog", "FeatureFlag")

    batch_size = 500
    updated = []

    for flag in FeatureFlag.objects.exclude(filters=None).iterator(chunk_size=batch_size):
        filters = flag.filters

        if not isinstance(filters, dict):
            continue

        groups = filters.get("groups") or []
        if not isinstance(groups, list):
            continue

        changed = False

        for group in groups:
            if not isinstance(group, dict):
                continue
            for prop in group.get("properties") or []:
                if not isinstance(prop, dict) or prop.get("type") != "cohort":
                    continue
                operator = prop.get("operator")
                if operator in VALID_COHORT_OPERATORS:
                    continue
                prop["operator"] = "not_in" if operator == "is_not" else "in"
                changed = True

        if changed:
            flag.filters = filters
            updated.append(flag)

        if len(updated) >= batch_size:
            FeatureFlag.objects.bulk_update(updated, ["filters"])
            updated = []

    if updated:
        FeatureFlag.objects.bulk_update(updated, ["filters"])


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1145_alter_integration_kind"),
    ]

    operations = [
        migrations.RunPython(
            normalize_cohort_flag_operators,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
