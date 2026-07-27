from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1224_columnconfiguration_properties")]

    operations = [
        migrations.AddField(
            model_name="team",
            name="llm_gateway_overspend_allowance_usd",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True),
        ),
        # Plain AddConstraint (not NOT-VALID) is safe here: the column is brand-new and all-NULL,
        # so validation scans nothing that fails and the lock is brief.
        migrations.AddConstraint(
            model_name="team",
            constraint=models.CheckConstraint(
                name="llm_gateway_overspend_allowance_usd_in_range",
                condition=models.Q(llm_gateway_overspend_allowance_usd__isnull=True)
                | models.Q(
                    llm_gateway_overspend_allowance_usd__gte=0,
                    llm_gateway_overspend_allowance_usd__lte=10000,
                ),
            ),
        ),
    ]
