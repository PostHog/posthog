"""DB-integration tests for the Deployments models.

Focus on invariants the migration adds: the partial unique constraint
that enforces "one active deploy per project", the soft-delete-aware
slug uniqueness on DeploymentProject, and the `current_deployment`
pointer's null-safety.
"""

from __future__ import annotations

from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction
from django.utils import timezone

from products.deployments.backend.models import Deployment, DeploymentEvent, DeploymentProject
from products.deployments.backend.test._helpers import DeploymentsTeamScopedTestMixin


class TestDeploymentProject(DeploymentsTeamScopedTestMixin, BaseTest):
    def _make_project(
        self,
        slug: str = "alpha",
        *,
        github_repo_id: int | None = None,
    ) -> DeploymentProject:
        return DeploymentProject.objects.create(
            team_id=self.team.id,
            name=f"Project {slug}",
            slug=slug,
            repo_url="https://github.com/example-org/site",
            default_branch="main",
            github_repo_id=github_repo_id,
            cloudflare_project_name=f"{self.team.id}-{slug}",
            subdomain=f"{slug}.posthog-app.com",
            cloudflare_ready_at=timezone.now(),
        )

    def test_slug_uniqueness_per_team(self) -> None:
        self._make_project(slug="alpha")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._make_project(slug="alpha")

    def test_soft_deleted_project_releases_slug(self) -> None:
        original = self._make_project(slug="alpha")
        original.deleted = True
        original.deleted_at = timezone.now()
        original.save(update_fields=["deleted", "deleted_at"])

        # The partial unique constraint excludes soft-deleted rows so the
        # slug can be reused.
        reused = self._make_project(slug="alpha")
        self.assertNotEqual(reused.pk, original.pk)

    def test_github_repo_uniqueness_per_team(self) -> None:
        self._make_project(slug="alpha", github_repo_id=42)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._make_project(slug="beta", github_repo_id=42)

    def test_soft_deleted_project_releases_github_repo(self) -> None:
        original = self._make_project(slug="alpha", github_repo_id=42)
        original.deleted = True
        original.deleted_at = timezone.now()
        original.save(update_fields=["deleted", "deleted_at"])

        reused = self._make_project(slug="beta", github_repo_id=42)
        self.assertNotEqual(reused.pk, original.pk)

    def test_projects_without_github_repo_id_are_not_repo_constrained(self) -> None:
        self._make_project(slug="alpha")
        project = self._make_project(slug="beta")

        self.assertIsNone(project.github_repo_id)

    def test_current_deployment_accepts_null(self) -> None:
        project = self._make_project()
        self.assertIsNone(project.current_deployment_id)

    def test_current_deployment_set_null_on_target_delete(self) -> None:
        project = self._make_project()
        deployment = Deployment.objects.create(
            project=project,
            team_id=self.team.id,
            status=Deployment.Status.READY.value,
            commit_sha="abcdef0123456789",
        )
        project.current_deployment = deployment
        project.save(update_fields=["current_deployment"])

        deployment.delete()
        project.refresh_from_db(fields=["current_deployment"])
        self.assertIsNone(project.current_deployment_id)


class TestDeploymentActiveConstraint(DeploymentsTeamScopedTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.deployment_project = DeploymentProject.objects.create(
            team_id=self.team.id,
            name="Site",
            slug="site",
            repo_url="https://github.com/example-org/site",
            cloudflare_project_name=f"{self.team.id}-site",
            subdomain="site.posthog-app.com",
            cloudflare_ready_at=timezone.now(),
        )

    def _make_deployment(self, status: Deployment.Status) -> Deployment:
        return Deployment.objects.create(
            project=self.deployment_project,
            team_id=self.team.id,
            status=status.value,
            commit_sha="a" * 40,
        )

    def test_second_non_terminal_deployment_raises(self) -> None:
        self._make_deployment(Deployment.Status.QUEUED)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._make_deployment(Deployment.Status.BUILDING)

    def test_terminal_then_non_terminal_is_allowed(self) -> None:
        self._make_deployment(Deployment.Status.READY)
        # No exception expected — the terminal row doesn't count against
        # the partial unique constraint.
        self._make_deployment(Deployment.Status.QUEUED)

    def test_multiple_terminals_allowed(self) -> None:
        # Most projects accumulate many terminal-status deployments over
        # their lifetime — the constraint must not block this.
        for _ in range(5):
            self._make_deployment(Deployment.Status.READY)


class TestDeploymentEvent(DeploymentsTeamScopedTestMixin, BaseTest):
    def test_event_is_team_scoped(self) -> None:
        project = DeploymentProject.objects.create(
            team_id=self.team.id,
            name="P",
            slug="p",
            repo_url="https://github.com/example-org/p",
        )
        deployment = Deployment.objects.create(
            project=project,
            team_id=self.team.id,
            status=Deployment.Status.READY.value,
        )
        event = DeploymentEvent.objects.create(
            deployment=deployment,
            team_id=self.team.id,
            event_type="status_changed",
            payload={"from": "building", "to": "ready"},
        )

        fetched = DeploymentEvent.objects.get(pk=event.pk)
        self.assertEqual(fetched.team_id, self.team.id)
        self.assertEqual(fetched.deployment_id, deployment.pk)
        self.assertEqual(fetched.payload["to"], "ready")
