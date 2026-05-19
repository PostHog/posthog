"""Add the deployment(project, -created_at) index without locking.

`AddIndex` on the existing `deployment` table would acquire a SHARE lock
for the duration of the index build. `AddIndexConcurrently` (Postgres
`CREATE INDEX CONCURRENTLY`) builds the index in the background without
blocking writes — the trade-off is that the migration runs outside a
transaction, so `atomic = False` is required and a failed run leaves an
INVALID index that must be DROPped manually.

Split from `0002` so the schema-creating migration can keep its
`atomic = True` rollback safety. PostHog policy explicitly flags mixing
CONCURRENTLY operations with regular DDL in one migration (see
`posthog/management/migration_analysis/policies.py`).
"""

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("deployments", "0002_deploymentproject_deploymentevent_and_more"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="deployment",
            index=models.Index(fields=("project", "-created_at"), name="deploy_project_created_idx"),
        ),
    ]
