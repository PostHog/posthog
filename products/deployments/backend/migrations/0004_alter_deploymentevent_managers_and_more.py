# Reconcile migration state with the current Django version.
#
# `0002` was generated under Django 4.2 and predates two changes that
# Django 5.2's autodetector now picks up against the current model
# definitions in `models.py`:
#
# 1. `ProductTeamModel` exposes a sibling `all_teams = models.Manager()`
#    alongside `objects`. `0002`'s `CreateModel` for `DeploymentEvent`
#    didn't record it, so we add the manager here via
#    `AlterModelManagers`. State-only — no SQL emitted. This mirrors
#    `products/visual_review/backend/migrations/0011_alter_artifact_managers_and_more.py`.
#
# 2. The auto-name hash for unnamed `Meta.indexes` entries changed
#    between Django 4.2 and 5.2. Renaming via Postgres `ALTER INDEX
#    ... RENAME TO ...` is a metadata-only operation (no table lock,
#    no rewrite), so this is safe to run inline.

import django.db.models.manager
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("deployments", "0003_deployment_project_idx_concurrent"),
    ]

    operations = [
        migrations.AlterModelManagers(
            name="deploymentevent",
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
        migrations.RenameIndex(
            model_name="deploymentevent",
            new_name="deployments_deploym_dd5504_idx",
            old_name="deployments_deploym_3a8e69_idx",
        ),
        migrations.RenameIndex(
            model_name="deploymentproject",
            new_name="deployments_team_id_849b3e_idx",
            old_name="deployments_team_id_e8b09b_idx",
        ),
    ]
