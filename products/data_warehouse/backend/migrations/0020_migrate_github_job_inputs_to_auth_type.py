from django.db import migrations


def migrate_github_job_inputs(apps, schema_editor):
    ExternalDataSource = apps.get_model("data_warehouse", "ExternalDataSource")

    for source in ExternalDataSource.objects.filter(source_type="Github", deleted=False):
        job_inputs = source.job_inputs
        if not isinstance(job_inputs, dict):
            continue

        # Already migrated
        if "auth_type" in job_inputs:
            continue

        if "personal_access_token" in job_inputs:
            pat = job_inputs.pop("personal_access_token")
            job_inputs["auth_type"] = {
                "selection": "pat",
                "personal_access_token": pat,
            }
        elif "github_integration_id" in job_inputs:
            integration_id = job_inputs.pop("github_integration_id")
            job_inputs["auth_type"] = {
                "selection": "oauth",
                "github_integration_id": integration_id,
            }

        source.job_inputs = job_inputs
        source.save(update_fields=["job_inputs"])


def reverse_migrate_github_job_inputs(apps, schema_editor):
    ExternalDataSource = apps.get_model("data_warehouse", "ExternalDataSource")

    for source in ExternalDataSource.objects.filter(source_type="Github", deleted=False):
        job_inputs = source.job_inputs
        if not isinstance(job_inputs, dict):
            continue

        auth_type = job_inputs.get("auth_type")
        if not isinstance(auth_type, dict):
            continue

        if auth_type.get("selection") == "pat":
            job_inputs["personal_access_token"] = auth_type.get("personal_access_token", "")
        elif auth_type.get("selection") == "oauth":
            job_inputs["github_integration_id"] = auth_type.get("github_integration_id")

        job_inputs.pop("auth_type", None)
        source.job_inputs = job_inputs
        source.save(update_fields=["job_inputs"])


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0019_fix_orphaned_tables"),
    ]

    operations = [
        migrations.RunPython(migrate_github_job_inputs, reverse_migrate_github_job_inputs),
    ]
