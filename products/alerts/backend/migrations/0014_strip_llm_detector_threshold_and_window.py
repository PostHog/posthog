from django.db import migrations


def strip_llm_detector_threshold_and_window(apps, schema_editor):
    """The AI detector no longer has a confidence threshold or a window. Its config schema
    forbids unknown keys, so a stored AI config that keeps them fails validation on its next edit."""
    AlertConfiguration = apps.get_model("alerts", "AlertConfiguration")
    alerts = AlertConfiguration.objects.filter(detector_config__type="llm").only("id", "detector_config")
    for alert in alerts.iterator(chunk_size=500):
        config = alert.detector_config
        if not isinstance(config, dict) or ("threshold" not in config and "window" not in config):
            continue
        stripped = {key: value for key, value in config.items() if key not in ("threshold", "window")}
        AlertConfiguration.objects.filter(id=alert.id).update(detector_config=stripped)


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0013_alertconfiguration_owner"),
    ]

    operations = [
        migrations.RunPython(strip_llm_detector_threshold_and_window, migrations.RunPython.noop, elidable=True),
    ]
