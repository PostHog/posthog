from django.db import migrations


def move_default_cooldowns_to_daily(apps, schema_editor):
    """Count-triggered reports still on the old one-hour default move to one report a day.

    A report someone set to exactly one hour cannot be told apart from the default, so it moves too.
    """
    EvaluationReport = apps.get_model("ai_observability", "EvaluationReport")
    EvaluationReport.objects.filter(frequency="every_n", cooldown_minutes=60).update(cooldown_minutes=60 * 24)


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0078_evaluation_report_daily_cooldown"),
    ]

    operations = [
        # Lossy: the old default and an explicit one-hour setting look the same, so reverse is a no-op.
        migrations.RunPython(move_default_cooldowns_to_daily, migrations.RunPython.noop),
    ]
