from django.db import migrations


def migrate_github_job_inputs(apps, schema_editor):
    ExternalDataSource = apps.get_model("data_warehouse", "ExternalDataSource")

    for source in ExternalDataSource.objects.filter(source_type="Github", deleted=False):
        job_inputs = source.job_inputs
        if not isinstance(job_inputs, dict):
            continue

        # Already migrated
        if "auth_method" in job_inputs:
            continue

        if "personal_access_token" in job_inputs:
            pat = job_inputs.pop("personal_access_token")
            job_inputs["auth_method"] = {
                "selection": "pat",
                "personal_access_token": pat,
            }
        elif "github_integration_id" in job_inputs:
            integration_id = job_inputs.pop("github_integration_id")
            job_inputs["auth_method"] = {
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

        auth_method = job_inputs.get("auth_method")
        if not isinstance(auth_method, dict):
            continue

        if auth_method.get("selection") == "pat":
            job_inputs["personal_access_token"] = auth_method.get("personal_access_token", "")
        elif auth_method.get("selection") == "oauth":
            job_inputs["github_integration_id"] = auth_method.get("github_integration_id")

        job_inputs.pop("auth_method", None)
        source.job_inputs = job_inputs
        source.save(update_fields=["job_inputs"])


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0019_fix_orphaned_tables"),
    ]

    operations = [
        migrations.RunPython(migrate_github_job_inputs, reverse_migrate_github_job_inputs),
    ]
