from django.db import migrations


def _clean_subdomain(value: object) -> str | None:
    # `str(None)` has been observed persisted in the outer `subdomain` slot on affected
    # rows; treat it as absent so we don't carry garbage forward.
    if isinstance(value, str) and value and value != "None":
        return value
    return None


def forwards(apps, schema_editor):
    ExternalDataSource = apps.get_model("data_warehouse", "ExternalDataSource")

    for source in ExternalDataSource.objects.filter(source_type="Vitally"):
        job_inputs = source.job_inputs
        if not isinstance(job_inputs, dict):
            continue

        region = job_inputs.get("region")
        if not isinstance(region, dict):
            continue

        selection = region.get("selection")
        if not isinstance(selection, dict):
            # Already in the canonical shape.
            continue

        inner_selection = selection.get("selection")
        if inner_selection not in ("EU", "US"):
            # Can't confidently recover — leave it so it shows up in any audit.
            continue

        # Prefer the outer subdomain if usable; fall back to the inner one.
        subdomain = _clean_subdomain(region.get("subdomain")) or _clean_subdomain(selection.get("subdomain")) or ""

        job_inputs["region"] = {"selection": inner_selection, "subdomain": subdomain}
        source.job_inputs = job_inputs
        source.save(update_fields=["job_inputs"])


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0045_alter_externaldatasource_source_type"),
    ]

    operations = [
        # Irreversible data fix — the corrupted shape is already the result of an
        # earlier rewrite, so reversing would just re-corrupt.
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
