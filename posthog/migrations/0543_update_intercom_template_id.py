# Generated by Django 4.2.15 on 2025-01-15 11:40

from django.db import migrations


def update_intercom_template_id(apps, schema_editor):
    HogFunction = apps.get_model("posthog", "HogFunction")
    HogFunction.objects.filter(template_id="template-Intercom").update(template_id="template-intercom")


def reverse_intercom_template_id(apps, schema_editor):
    HogFunction = apps.get_model("posthog", "HogFunction")
    HogFunction.objects.filter(template_id="template-intercom").update(template_id="template-Intercom")


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0542_alter_integration_kind"),
    ]

    operations = [
        migrations.RunPython(
            update_intercom_template_id,
            reverse_intercom_template_id,
        ),
    ]
