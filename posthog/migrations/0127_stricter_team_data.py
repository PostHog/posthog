# Generated by Django 3.0.6 on 2021-02-09 09:11

from django.db import migrations, models


def adjust_teams_for_stricter_requirements(apps, schema_editor):
    Team = apps.get_model("posthog", "Team")
    Organization = apps.get_model("posthog", "Organization")
    first_organization = Organization.objects.order_by("id").first()
    if first_organization is not None:
        Team.objects.filter(organization_id__isnull=True).update(organization_id=first_organization.id)
    else:
        Team.objects.filter(organization_id__isnull=True).delete()
    Team.objects.filter(models.Q(name__isnull=True) | models.Q(name="")).update(name="Project X")


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0126_fix_funnels_insights_links"),
    ]

    operations = [
        migrations.RunPython(adjust_teams_for_stricter_requirements, migrations.RunPython.noop),
    ]
