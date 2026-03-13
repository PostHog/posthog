from django.db import migrations


def rename_slack_twig_to_posthog_code(apps, schema_editor):
    Integration = apps.get_model("posthog", "Integration")
    Integration.objects.filter(kind="slack-twig").update(kind="slack-posthog-code")


def rename_posthog_code_to_slack_twig(apps, schema_editor):
    Integration = apps.get_model("posthog", "Integration")
    Integration.objects.filter(kind="slack-posthog-code").update(kind="slack-twig")


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1049_alter_integration_kind_posthog_code"),
    ]

    operations = [
        migrations.RunPython(
            rename_slack_twig_to_posthog_code,
            rename_posthog_code_to_slack_twig,
        ),
    ]
