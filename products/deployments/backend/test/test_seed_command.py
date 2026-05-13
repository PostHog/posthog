"""Regression tests for the `seed_deployments` management command.

Catches the C3 finding from CODE_REVIEW.md: the seeder mixes SEED and
REDEPLOY trigger kinds, so a `trigger_kind=SEED`-only clear would leak
REDEPLOY rows across runs.
"""

from __future__ import annotations

from io import StringIO

from posthog.test.base import APIBaseTest

from django.core.management import call_command

from products.deployments.backend.models import Deployment, DeploymentProject
from products.deployments.backend.test._helpers import DeploymentsTeamScopedTestMixin


class TestSeedDeployments(DeploymentsTeamScopedTestMixin, APIBaseTest):
    def test_idempotent_across_runs(self) -> None:
        out = StringIO()
        call_command(
            "seed_deployments",
            team_id=self.team.id,
            project_count=1,
            deployments_per_project=15,
            seed=42,
            stdout=out,
        )
        project = DeploymentProject.objects.get(slug="marketing-site")
        first_count = Deployment.objects.filter(project=project).count()
        self.assertEqual(first_count, 15)

        # Re-run with the same args — counts should not drift.
        call_command(
            "seed_deployments",
            team_id=self.team.id,
            project_count=1,
            deployments_per_project=15,
            seed=42,
            stdout=out,
        )
        second_count = Deployment.objects.filter(project=project).count()
        self.assertEqual(second_count, first_count)
