from django.db import migrations

# Each feature flag action and the experiment action that will replace it once experiment-owned
# flags leave `feature_flag.*` scope. Copying now, ahead of that change, keeps organizations with
# existing policies at the coverage they have today.
ACTION_MAP = {
    "feature_flag.enable": "experiment.launch",
    "feature_flag.disable": "experiment.pause",
    "feature_flag.update": "experiment.update",
}

COPIED_FIELDS = (
    "organization_id",
    "team_id",
    "conditions",
    "approver_config",
    "allow_self_approve",
    "bypass_org_membership_levels",
    "expires_after",
    "enabled",
    "created_by_id",
)


def copy_policies(apps, schema_editor):
    ApprovalPolicy = apps.get_model("approvals", "ApprovalPolicy")

    for source_action, target_action in ACTION_MAP.items():
        for policy in ApprovalPolicy.objects.filter(action_key=source_action):
            # A policy is scoped to a team, so copy per row rather than per organization.
            if ApprovalPolicy.objects.filter(
                action_key=target_action,
                organization_id=policy.organization_id,
                team_id=policy.team_id,
            ).exists():
                continue

            copy = ApprovalPolicy.objects.create(
                action_key=target_action,
                **{field: getattr(policy, field) for field in COPIED_FIELDS},
            )
            # Dropping these would narrow who can bypass the copy relative to the source.
            copy.bypass_roles.set(policy.bypass_roles.all())


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0002_alter_changerequest_validation_status"),
    ]

    operations = [
        # The reverse keeps the copies rather than deleting by target key. `action_key` is
        # writable through the policy API, so such a delete would also remove a policy that
        # already held the target key and was skipped, and any policy a person writes later.
        # The copies are inert while the experiment actions are unregistered.
        migrations.RunPython(copy_policies, migrations.RunPython.noop),
    ]
