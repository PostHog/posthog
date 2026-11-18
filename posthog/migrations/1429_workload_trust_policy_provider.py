from django.db import migrations, models

import posthog.models.workload_trust_policy
from posthog.migration_helpers import AddConstraintNotValid, ValidateConstraint


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1428_oauth_device_grant_required_scope"),
    ]

    # GitHub Actions was the only provider any existing row could have been written for, so the
    # constant default backfills every row correctly without a table rewrite.
    operations = [
        migrations.AddField(
            model_name="workloadtrustpolicy",
            name="provider",
            field=models.CharField(
                choices=posthog.models.workload_trust_policy.workload_provider_choices,
                default="github_actions",
                max_length=64,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="workloadtrustpolicyrequest",
            name="provider",
            field=models.CharField(
                choices=posthog.models.workload_trust_policy.workload_provider_choices,
                default="github_actions",
                max_length=64,
            ),
            preserve_default=False,
        ),
        AddConstraintNotValid(
            model_name="workloadtrustpolicy",
            constraint=models.CheckConstraint(
                condition=models.Q(("provider", ""), _negated=True), name="posthog_workload_policy_provider_set"
            ),
        ),
        AddConstraintNotValid(
            model_name="workloadtrustpolicyrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(("provider", ""), _negated=True), name="posthog_workload_request_provider_set"
            ),
        ),
        ValidateConstraint(model_name="workloadtrustpolicy", name="posthog_workload_policy_provider_set"),
        ValidateConstraint(model_name="workloadtrustpolicyrequest", name="posthog_workload_request_provider_set"),
    ]
