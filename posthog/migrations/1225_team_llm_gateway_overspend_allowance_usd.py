from django.contrib.postgres.operations import AddConstraintNotValid, ValidateConstraint
from django.db import migrations, models


class Migration(migrations.Migration):
    # atomic=False so the NOT VALID add and the VALIDATE run in separate transactions, keeping each
    # lock short on the large posthog_team table (matches project_id_is_not_null). The column is
    # brand-new and all-NULL, so validation is instant.
    atomic = False

    dependencies = [("posthog", "1224_columnconfiguration_properties")]

    operations = [
        migrations.AddField(
            model_name="team",
            name="llm_gateway_overspend_allowance_usd",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True),
        ),
        AddConstraintNotValid(
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
        ValidateConstraint(model_name="team", name="llm_gateway_overspend_allowance_usd_in_range"),
    ]
