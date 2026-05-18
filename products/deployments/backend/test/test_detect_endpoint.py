"""HTTP-level tests for `POST /deployment_projects/detect/`."""

from __future__ import annotations

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.deployments.backend.test._helpers import DeploymentsTeamScopedTestMixin


class _BaseDetectTest(DeploymentsTeamScopedTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._flag_patcher = patch(
            "products.deployments.backend.access.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self._flag_patcher.start()
        self.addCleanup(self._flag_patcher.stop)

    @property
    def _detect_url(self) -> str:
        return f"/api/projects/{self.team.id}/deployment_projects/detect/"


class TestDetectEndpoint(_BaseDetectTest):
    def test_returns_suggested_config_for_known_framework(self) -> None:
        response = self.client.post(
            self._detect_url,
            data={
                "package_json": {"dependencies": {"vite": "^5"}, "engines": {"node": ">=20"}},
                "lockfiles": ["pnpm-lock.yaml"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        body = response.json()
        self.assertEqual(body["framework"], "vite")
        self.assertEqual(body["package_manager"], "pnpm")
        self.assertEqual(body["install_command"], "pnpm install --frozen-lockfile")
        self.assertEqual(body["build_command"], "pnpm build")
        self.assertEqual(body["output_dir"], "dist")
        self.assertEqual(body["node_version"], "20")

    def test_plain_html_repo_returns_null_framework_and_empty_build(self) -> None:
        # Real case — a static-site repo with no package.json. Endpoint must
        # not 500 and must return `framework=None` so the UI saves null into
        # `DeploymentProject.framework` rather than the literal string
        # "plain", letting the build worker do its own thing.
        response = self.client.post(
            self._detect_url,
            data={"lockfiles": []},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        body = response.json()
        self.assertIsNone(body["framework"])
        self.assertEqual(body["build_command"], "")
        self.assertEqual(body["install_command"], "")
        self.assertEqual(body["output_dir"], ".")


class TestDetectEndpointFeatureFlag(DeploymentsTeamScopedTestMixin, APIBaseTest):
    # Separate class so this one *doesn't* force the flag on.
    def test_returns_403_when_feature_flag_off(self) -> None:
        with patch(
            "products.deployments.backend.access.posthoganalytics.feature_enabled",
            return_value=False,
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/deployment_projects/detect/",
                data={"lockfiles": []},
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
