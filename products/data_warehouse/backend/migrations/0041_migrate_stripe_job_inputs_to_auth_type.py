from django.db import migrations


def migrate_stripe_job_inputs(apps, schema_editor):
    ExternalDataSource = apps.get_model("data_warehouse", "ExternalDataSource")

    for source in ExternalDataSource.objects.filter(source_type="Stripe"):
        job_inputs = source.job_inputs
        if not isinstance(job_inputs, dict):
            continue

        # Already migrated
        if "auth_method" in job_inputs:
            continue

        if "stripe_secret_key" in job_inputs:
            secret_key = job_inputs.pop("stripe_secret_key")
            job_inputs["auth_method"] = {
                "selection": "api_key",
                "stripe_secret_key": secret_key,
            }
        elif "stripe_integration_id" in job_inputs:
            integration_id = job_inputs.pop("stripe_integration_id")
            job_inputs["auth_method"] = {
                "selection": "oauth",
                "stripe_integration_id": integration_id,
            }

        source.job_inputs = job_inputs
        source.save(update_fields=["job_inputs"])


def reverse_migrate_stripe_job_inputs(apps, schema_editor):
    ExternalDataSource = apps.get_model("data_warehouse", "ExternalDataSource")

    for source in ExternalDataSource.objects.filter(source_type="Stripe"):
        job_inputs = source.job_inputs
        if not isinstance(job_inputs, dict):
            continue

        # Reverted and/or not migrated yet
        auth_method = job_inputs.get("auth_method")
        if not isinstance(auth_method, dict):
            continue

        if auth_method.get("selection") == "api_key":
            job_inputs["stripe_secret_key"] = auth_method.get("stripe_secret_key", "")
        elif auth_method.get("selection") == "oauth":
            integration_id = auth_method.get("stripe_integration_id")
            if integration_id:
                job_inputs["stripe_integration_id"] = integration_id

        job_inputs.pop("auth_method", None)
        source.job_inputs = job_inputs
        source.save(update_fields=["job_inputs"])


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0040_saved_query_folders"),
    ]

    operations = [
        migrations.RunPython(migrate_stripe_job_inputs, reverse_migrate_stripe_job_inputs),
    ]
