"""Add the deployment(project, -created_at) index without locking.

`AddIndex` on the existing `deployment` table would acquire a SHARE lock
for the duration of the index build. `CreateIndexConcurrently` builds the
index in the background and recovers from invalid indexes left by interrupted
builds.

Split from `0002` so the schema-creating migration can keep its
`atomic = True` rollback safety. PostHog policy explicitly flags mixing
CONCURRENTLY operations with regular DDL in one migration (see
`posthog/management/migration_analysis/policies.py`).
"""

from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("deployments", "0002_deploymentproject_deploymentevent_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="deployment",
                    index=models.Index(fields=("project", "-created_at"), name="deploy_project_created_idx"),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="deploy_project_created_idx",
                    table_name="deployments_deployment",
                    columns="(project_id, created_at DESC)",
                ),
            ],
        ),
    ]
