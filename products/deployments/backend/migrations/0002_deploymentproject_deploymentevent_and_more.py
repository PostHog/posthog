"""Add DeploymentProject + DeploymentEvent + the remaining Deployment fields.

This migration extends the scaffold's single-model `Deployment` to the
three-model design from the deployments.md spec:

- DeploymentProject — connected repo + Cloudflare target + build config.
- DeploymentEvent — append-only audit log per deployment.
- Deployment.project (FK), error_*, cloudflare_*, temporal_*, MANUAL trigger.
- Partial unique constraint enforcing "one active deploy per project".

Safety notes:
- `Deployment.project` is added as a NOT NULL FK. The Deployment table is
  empty in production at the time this lands (brand-new product), so the
  implicit "rewrite-table-with-default" cost is zero. If by deploy time
  there happen to be rows, this migration will refuse to apply — by
  design — and we'll split it into a phased version before shipping.
- Indexes use `AddIndex` (not Concurrently) because the tables are
  either new (DeploymentProject, DeploymentEvent) or empty (Deployment).
- The partial unique constraint validates against zero rows, so it's
  instant.
- `current_deployment` on `DeploymentProject` is a circular FK to
  `Deployment`; the string-reference + null=True lets Django resolve
  both directions within this single migration without a separate
  `AddField` operation.
"""

import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("deployments", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeploymentProject",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("team_id", models.BigIntegerField(db_index=True)),
                ("created_by_id", models.BigIntegerField(blank=True, null=True)),
                ("name", models.CharField(max_length=200)),
                ("slug", models.SlugField(max_length=80)),
                ("repo_url", models.URLField(max_length=1024)),
                ("default_branch", models.CharField(default="main", max_length=255)),
                ("github_integration_id", models.BigIntegerField(blank=True, null=True)),
                ("build_command", models.TextField(blank=True, default=None, null=True)),
                ("output_dir", models.CharField(default="dist", max_length=255)),
                ("framework", models.CharField(blank=True, max_length=50, null=True)),
                ("inject_posthog_snippet", models.BooleanField(default=False)),
                ("cloudflare_project_name", models.CharField(blank=True, default="", max_length=255)),
                ("subdomain", models.CharField(blank=True, default="", max_length=255)),
                ("cloudflare_ready_at", models.DateTimeField(blank=True, null=True)),
                # current_deployment is set after Deployment.project FK is added below.
                # String-ref + null=True avoids the circular-FK chicken-and-egg.
                (
                    "current_deployment",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="deployments.deployment",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted", models.BooleanField(blank=True, default=False, null=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="DeploymentEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("team_id", models.BigIntegerField(db_index=True)),
                (
                    "deployment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="deployments.deployment",
                    ),
                ),
                ("event_type", models.CharField(max_length=50)),
                ("payload", models.JSONField(default=dict)),
                ("occurred_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ("-occurred_at",),
            },
        ),
        # Deployment.project — NOT NULL FK, safe to add directly because the
        # table is empty at rollout time. If it isn't, this will fail loudly.
        migrations.AddField(
            model_name="deployment",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="deployments",
                to="deployments.deploymentproject",
            ),
        ),
        migrations.AddField(
            model_name="deployment",
            name="triggered_by_user_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="deployment",
            name="error_message",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="deployment",
            name="error_step",
            field=models.CharField(
                blank=True,
                choices=[
                    ("dispatch", "Dispatch"),
                    ("clone", "Clone"),
                    ("install", "Install"),
                    ("build", "Build"),
                    ("publish", "Publish"),
                ],
                default="",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="deployment",
            name="cloudflare_deployment_id",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="deployment",
            name="temporal_workflow_id",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="deployment",
            name="temporal_run_id",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        # Expand trigger_kind choices to include MANUAL and bump default
        # to MANUAL (most common path in v1 — user-clicked Deploy).
        migrations.AlterField(
            model_name="deployment",
            name="trigger_kind",
            field=models.CharField(
                choices=[
                    ("manual", "Manual"),
                    ("git", "Git"),
                    ("redeploy", "Redeploy"),
                    ("rollback", "Rollback"),
                    ("seed", "Seed"),
                ],
                default="manual",
                max_length=16,
            ),
        ),
        migrations.AddIndex(
            model_name="deploymentproject",
            index=models.Index(fields=["team_id", "-created_at"], name="deployments_team_id_e8b09b_idx"),
        ),
        migrations.AddIndex(
            model_name="deploymentevent",
            index=models.Index(fields=["deployment", "occurred_at"], name="deployments_deploym_3a8e69_idx"),
        ),
        migrations.AddIndex(
            model_name="deployment",
            index=models.Index(fields=("project", "-created_at"), name="deploy_project_created_idx"),
        ),
        # Slug uniqueness scoped to live rows. The OR-isnull clause covers
        # the bool-with-null=True pattern used by DeletedMetaFields, where
        # `deleted` defaults to False but is nullable.
        migrations.AddConstraint(
            model_name="deploymentproject",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted", False)) | models.Q(("deleted__isnull", True)),
                fields=("team_id", "slug"),
                name="unique_deploymentproject_slug_per_team",
            ),
        ),
        # At-most-one non-terminal deploy per project. The 409 the API returns
        # is the friendly surface over the resulting IntegrityError; no
        # check-then-insert (which would race).
        migrations.AddConstraint(
            model_name="deployment",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status__in", ("queued", "initializing", "building"))),
                fields=("project",),
                name="one_active_deployment_per_project",
            ),
        ),
    ]
