from typing import Any

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.workload_identity.resolvers import resolve_github_repository, resolve_gitlab_project
from posthog.workload_identity.subjects import (
    ResolvedWorkloadSubject,
    WorkloadSubjectLookupUnavailable,
    WorkloadSubjectNotFound,
)


def _response(status_code: int, body: Any = None) -> MagicMock:
    return MagicMock(status_code=status_code, json=MagicMock(return_value=body))


PUBLIC_REPO = {"id": 1234, "full_name": "Acme/Web", "private": False}


class TestResolveGitHubRepository(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "through_the_teams_integration",
                _response(200, {**PUBLIC_REPO, "private": True}),
                None,
                ResolvedWorkloadSubject(subject="1234", subject_name="Acme/Web", found_via="your GitHub integration"),
            ),
            (
                "public_repository_without_an_integration",
                None,
                _response(200, PUBLIC_REPO),
                ResolvedWorkloadSubject(subject="1234", subject_name="Acme/Web", found_via="GitHub"),
            ),
            # PostHog's own token can see repositories that aren't public, which a team must not learn about.
            (
                "private_repository_seen_by_posthogs_token",
                None,
                _response(200, {**PUBLIC_REPO, "private": True}),
                WorkloadSubjectNotFound,
            ),
            ("missing_repository", None, _response(404, {}), WorkloadSubjectNotFound),
            ("github_rate_limit", None, _response(403, {}), WorkloadSubjectLookupUnavailable),
            # A broken installation must not stop the public lookup, but a miss then proves nothing.
            (
                "public_repository_while_the_integration_is_down",
                GitHubIntegrationError("token refresh failed"),
                _response(200, PUBLIC_REPO),
                ResolvedWorkloadSubject(subject="1234", subject_name="Acme/Web", found_via="GitHub"),
            ),
            (
                "missing_repository_while_the_integration_is_down",
                GitHubIntegrationError("token refresh failed"),
                _response(404, {}),
                WorkloadSubjectLookupUnavailable,
            ),
        ]
    )
    def test_looks_up_the_repository(
        self, _name: str, integration: MagicMock | Exception | None, public_response: MagicMock | None, expected: Any
    ) -> None:
        integrations = [] if integration is None else [MagicMock()]
        github = MagicMock()
        if isinstance(integration, Exception):
            github.api_request.side_effect = integration
        else:
            github.api_request.return_value = integration
        with (
            patch("posthog.workload_identity.resolvers.Integration") as model,
            patch("posthog.workload_identity.resolvers.GitHubIntegration", return_value=github),
            patch("posthog.workload_identity.resolvers.github_request", return_value=public_response) as public,
        ):
            model.objects.filter.return_value.order_by.return_value = integrations
            if isinstance(expected, type):
                with self.assertRaises(expected):
                    resolve_github_repository(1, "acme/web")
            else:
                assert resolve_github_repository(1, "git@github.com:acme/web.git") == expected

        assert public.called is not isinstance(integration, MagicMock)

    def test_refuses_a_name_that_could_reach_another_github_endpoint(self) -> None:
        with (
            patch("posthog.workload_identity.resolvers.Integration") as integration,
            patch("posthog.workload_identity.resolvers.github_request") as public,
        ):
            with self.assertRaises(WorkloadSubjectNotFound):
                resolve_github_repository(1, "acme/web/contents/secrets?ref=main")

        assert not integration.called
        assert not public.called


PUBLIC_PROJECT = {"id": 42, "path_with_namespace": "Acme/Tools/Web", "visibility": "public"}


@override_settings(GITLAB_TOKEN="glpat-posthog")
class TestResolveGitLabProject(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "through_the_teams_integration",
                _response(200, {**PUBLIC_PROJECT, "visibility": "private"}),
                None,
                ResolvedWorkloadSubject(
                    subject="42", subject_name="Acme/Tools/Web", found_via="your GitLab integration"
                ),
            ),
            (
                "public_project_without_an_integration",
                None,
                _response(200, PUBLIC_PROJECT),
                ResolvedWorkloadSubject(subject="42", subject_name="Acme/Tools/Web", found_via="GitLab"),
            ),
            # PostHog's own token can see projects that aren't public, which a team must not learn about.
            (
                "private_project_seen_by_posthogs_token",
                None,
                _response(200, {**PUBLIC_PROJECT, "visibility": "internal"}),
                WorkloadSubjectNotFound,
            ),
            ("gitlab_error", None, _response(502, {}), WorkloadSubjectLookupUnavailable),
        ]
    )
    def test_looks_up_the_project(
        self, _name: str, integration_response: MagicMock | None, public_response: MagicMock | None, expected: Any
    ) -> None:
        integration = MagicMock(
            config={"hostname": "https://gitlab.com"}, sensitive_config={"access_token": "glpat-team"}
        )
        calls: list[str] = []

        def request(method: str, url: str, *, token: str, **kwargs: Any) -> MagicMock | None:
            calls.append(token)
            return integration_response if token == "glpat-team" else public_response

        with (
            patch(
                "posthog.workload_identity.resolvers.IntegrationManager.gitlab.token.list",
                return_value=[integration] if integration_response is not None else [],
            ),
            patch(
                "posthog.workload_identity.resolvers.GitLabIntegration",
                side_effect=lambda record: MagicMock(integration=record, hostname="https://gitlab.com"),
            ),
            patch("posthog.workload_identity.resolvers.gitlab_request", side_effect=request),
        ):
            if isinstance(expected, type):
                with self.assertRaises(expected):
                    resolve_gitlab_project(1, "acme/tools/web")
            else:
                assert resolve_gitlab_project(1, "https://gitlab.com/acme/tools/web.git") == expected

        assert calls == (["glpat-team"] if integration_response is not None else ["glpat-posthog"])

    def test_refuses_a_path_that_could_reach_another_gitlab_endpoint(self) -> None:
        with patch("posthog.workload_identity.resolvers.gitlab_request") as request:
            with self.assertRaises(WorkloadSubjectNotFound):
                resolve_gitlab_project(1, "acme/../../users")

        assert not request.called
