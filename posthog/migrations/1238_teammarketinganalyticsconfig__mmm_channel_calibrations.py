from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1237_alter_integration_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="teammarketinganalyticsconfig",
            name="_mmm_channel_calibrations",
            field=models.JSONField(
                blank=True,
                db_column="mmm_channel_calibrations",
                default=dict,
                help_text="Marketing mix modeling lift-test calibrations per channel: {channel: {lift_pct, ci_low, ci_high, source, experiment_id}}. Used to derive Bayesian priors for the MMM fit.",
            ),
        ),
    ]
