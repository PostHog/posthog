from django.db import migrations

LEGACY_STRIPE_API_VERSION = "2024-09-30.acacia"


def _get_external_data_source(apps):
    # The model moved from data_warehouse to warehouse_sources. Try both so this works in
    # real migrate (historical apps registry) and in tests that pass the live registry.
    try:
        return apps.get_model("warehouse_sources", "ExternalDataSource")
    except LookupError:
        return apps.get_model("data_warehouse", "ExternalDataSource")


def set_default_stripe_api_version(apps, schema_editor):
    ExternalDataSource = _get_external_data_source(apps)

    for source in ExternalDataSource.objects.filter(source_type="Stripe"):
        job_inputs = source.job_inputs
        if not isinstance(job_inputs, dict):
            continue

        if "stripe_api_version" in job_inputs:
            continue

        job_inputs["stripe_api_version"] = LEGACY_STRIPE_API_VERSION
        source.job_inputs = job_inputs
        source.save(update_fields=["job_inputs"])


def reverse_set_default_stripe_api_version(apps, schema_editor):
    ExternalDataSource = _get_external_data_source(apps)

    for source in ExternalDataSource.objects.filter(source_type="Stripe"):
        job_inputs = source.job_inputs
        if not isinstance(job_inputs, dict):
            continue

        if job_inputs.get("stripe_api_version") != LEGACY_STRIPE_API_VERSION:
            continue

        job_inputs.pop("stripe_api_version", None)
        source.job_inputs = job_inputs
        source.save(update_fields=["job_inputs"])


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0057_managed_warehouse_backfill_partition"),
    ]

    operations = [
        migrations.RunPython(set_default_stripe_api_version, reverse_set_default_stripe_api_version),
    ]
