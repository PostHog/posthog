from typing import Any

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.redis import get_client
from posthog.token_bucket import BucketDecision
from posthog.workload_identity.resolvers import (
    GITHUB_PUBLIC_LOOKUP_BUCKET,
    GITLAB_PUBLIC_LOOKUP_BUCKET,
    resolve_github_repository,
    resolve_gitlab_project,
)
from posthog.workload_identity.subjects import (
    ResolvedWorkloadSubject,
    WorkloadSubjectLookupUnavailable,
    WorkloadSubjectNotFound,
)


def _response(status_code: int, body: Any = None) -> MagicMock:
    return MagicMock(status_code=status_code, json=MagicMock(return_value=body))


PUBLIC_REPO = {"id": 1234, "full_name": "Acme/Web", "private": False}


class TestResolveGitHubRepository(SimpleTestCase):
    def setUp(self) -> None:
        get_client().delete(GITHUB_PUBLIC_LOOKUP_BUCKET)

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
            (
                "missing_repository_while_the_installation_errors",
                _response(503, {}),
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
            patch(
                "posthog.workload_identity.resolvers.IntegrationManager.github.oauth.list", return_value=integrations
            ),
            patch("posthog.workload_identity.resolvers.GitHubIntegration", return_value=github),
            patch("posthog.workload_identity.resolvers.github_request", return_value=public_response) as public,
        ):
            if isinstance(expected, type):
                with self.assertRaises(expected):
                    resolve_github_repository(1, "acme/web")
            else:
                assert resolve_github_repository(1, "git@github.com:acme/web.git") == expected

        assert public.called is not (isinstance(integration, MagicMock) and integration.status_code == 200)

    def test_public_lookups_stop_once_the_shared_budget_is_used_up(self) -> None:
        with (
            patch("posthog.workload_identity.resolvers.IntegrationManager.github.oauth.list", return_value=[]),
            patch(
                "posthog.workload_identity.resolvers.consume",
                return_value=BucketDecision(allowed=False, remaining=0, limit=10, retry_after=60, reset=60),
            ),
            patch("posthog.workload_identity.resolvers.github_request") as public,
        ):
            with self.assertRaises(WorkloadSubjectLookupUnavailable):
                resolve_github_repository(1, "acme/web")

        assert not public.called

    def test_the_lookup_stops_asking_github_once_its_deadline_passes(self) -> None:
        github = MagicMock()
        github.api_request.return_value = _response(404, {})
        with (
            patch(
                "posthog.workload_identity.resolvers.IntegrationManager.github.oauth.list",
                return_value=[MagicMock(), MagicMock()],
            ),
            patch("posthog.workload_identity.resolvers.GitHubIntegration", return_value=github),
            patch("posthog.workload_identity.resolvers.github_request") as public,
            patch("posthog.workload_identity.resolvers.time") as clock,
        ):
            clock.monotonic.side_effect = [0.0, 3.0, 100.0, 100.0]
            with self.assertRaises(WorkloadSubjectLookupUnavailable):
                resolve_github_repository(1, "acme/web")

        assert github.api_request.call_count == 1
        assert github.api_request.call_args.kwargs["timeout"] == 10
        assert github.api_request.call_args.kwargs["retry_transient"] is False
        assert not public.called

    def test_refuses_a_name_that_could_reach_another_github_endpoint(self) -> None:
        with (
            patch("posthog.workload_identity.resolvers.IntegrationManager.github.oauth.list") as integration,
            patch("posthog.workload_identity.resolvers.github_request") as public,
        ):
            with self.assertRaises(WorkloadSubjectNotFound):
                resolve_github_repository(1, "acme/web/contents/secrets?ref=main")

        assert not integration.called
        assert not public.called


PUBLIC_PROJECT = {"id": 42, "path_with_namespace": "Acme/Tools/Web", "visibility": "public"}
GITLAB_COM_INTEGRATION = {"hostname": "https://gitlab.com", "project_id": 42}
OTHER_PROJECT_INTEGRATION = {"hostname": "https://gitlab.com", "project_id": 7}


class TestResolveGitLabProject(SimpleTestCase):
    def setUp(self) -> None:
        get_client().delete(GITLAB_PUBLIC_LOOKUP_BUCKET)

    @parameterized.expand(
        [
            (
                "connected_private_project",
                GITLAB_COM_INTEGRATION,
                _response(200, {**PUBLIC_PROJECT, "visibility": "private"}),
                None,
                ResolvedWorkloadSubject(
                    subject="42", subject_name="Acme/Tools/Web", found_via="your GitLab integration"
                ),
                ["glpat-team"],
            ),
            # A group or personal token sees more than the project it was connected for.
            (
                "another_private_project_the_integration_sees",
                OTHER_PROJECT_INTEGRATION,
                _response(200, {**PUBLIC_PROJECT, "visibility": "private"}),
                _response(200, {**PUBLIC_PROJECT, "visibility": "private"}),
                WorkloadSubjectNotFound,
                ["glpat-team", "glpat-posthog"],
            ),
            (
                "public_project_through_the_integration",
                OTHER_PROJECT_INTEGRATION,
                _response(200, PUBLIC_PROJECT),
                None,
                ResolvedWorkloadSubject(
                    subject="42", subject_name="Acme/Tools/Web", found_via="your GitLab integration"
                ),
                ["glpat-team"],
            ),
            (
                "public_project_after_a_revoked_integration_token",
                GITLAB_COM_INTEGRATION,
                _response(401, {}),
                _response(200, PUBLIC_PROJECT),
                ResolvedWorkloadSubject(subject="42", subject_name="Acme/Tools/Web", found_via="GitLab"),
                ["glpat-team", "glpat-posthog"],
            ),
            # A self-managed instance's token must never reach gitlab.com.
            (
                "self_managed_integration",
                {"hostname": "https://gitlab.example.com"},
                None,
                _response(200, PUBLIC_PROJECT),
                ResolvedWorkloadSubject(subject="42", subject_name="Acme/Tools/Web", found_via="GitLab"),
                ["glpat-posthog"],
            ),
            # PostHog's own token can see projects that aren't public, which a team must not learn about.
            (
                "private_project_seen_by_posthogs_token",
                None,
                None,
                _response(200, {**PUBLIC_PROJECT, "visibility": "internal"}),
                WorkloadSubjectNotFound,
                ["glpat-posthog"],
            ),
            ("gitlab_error", None, None, _response(502, {}), WorkloadSubjectLookupUnavailable, ["glpat-posthog"]),
            (
                "public_project_after_posthogs_token_expired",
                None,
                None,
                {"glpat-posthog": _response(401, {}), None: _response(200, PUBLIC_PROJECT)},
                ResolvedWorkloadSubject(subject="42", subject_name="Acme/Tools/Web", found_via="GitLab"),
                ["glpat-posthog", None],
            ),
        ]
    )
    @override_settings(GITLAB_TOKEN="glpat-posthog")
    def test_looks_up_the_project(
        self,
        _name: str,
        integration_config: dict[str, Any] | None,
        integration_response: MagicMock | None,
        public_response: MagicMock | dict[str | None, MagicMock] | None,
        expected: Any,
        tokens: list[str | None],
    ) -> None:
        integrations = (
            [MagicMock(kind="gitlab", config=integration_config, sensitive_config={"access_token": "glpat-team"})]
            if integration_config
            else []
        )
        calls: list[str | None] = []

        def request(method: str, url: str, *, token: str | None, **kwargs: Any) -> MagicMock | None:
            calls.append(token)
            if token == "glpat-team":
                return integration_response
            return public_response[token] if isinstance(public_response, dict) else public_response

        with (
            patch(
                "posthog.workload_identity.resolvers.IntegrationManager.gitlab.token.list", return_value=integrations
            ),
            patch("posthog.workload_identity.resolvers.gitlab_request", side_effect=request),
        ):
            if isinstance(expected, type):
                with self.assertRaises(expected):
                    resolve_gitlab_project(1, "acme/tools/web")
            else:
                assert resolve_gitlab_project(1, "acme/tools/web") == expected

        assert calls == tokens

    @parameterized.expand(
        [
            ("git_remote", "git@gitlab.com:acme/tools/web.git"),
            ("browser_url", "https://gitlab.com/acme/tools/web/-/tree/main"),
        ]
    )
    @override_settings(GITLAB_TOKEN=None)
    def test_asks_anonymously_for_the_path_people_paste(self, _name: str, name: str) -> None:
        with (
            patch("posthog.workload_identity.resolvers.IntegrationManager.gitlab.token.list", return_value=[]),
            patch(
                "posthog.workload_identity.resolvers.gitlab_request", return_value=_response(200, PUBLIC_PROJECT)
            ) as request,
        ):
            assert resolve_gitlab_project(1, name).subject == "42"

        assert request.call_args.args[1] == "https://gitlab.com/api/v4/projects/acme%2Ftools%2Fweb"
        assert request.call_args.kwargs["token"] is None

    def test_public_lookups_stop_once_the_shared_budget_is_used_up(self) -> None:
        with (
            patch("posthog.workload_identity.resolvers.IntegrationManager.gitlab.token.list", return_value=[]),
            patch(
                "posthog.workload_identity.resolvers.consume",
                return_value=BucketDecision(allowed=False, remaining=0, limit=10, retry_after=60, reset=60),
            ),
            patch("posthog.workload_identity.resolvers.gitlab_request") as public,
        ):
            with self.assertRaises(WorkloadSubjectLookupUnavailable):
                resolve_gitlab_project(1, "acme/tools/web")

        assert not public.called

    def test_refuses_a_path_that_could_reach_another_gitlab_endpoint(self) -> None:
        with patch("posthog.workload_identity.resolvers.gitlab_request") as request:
            with self.assertRaises(WorkloadSubjectNotFound):
                resolve_gitlab_project(1, "acme/../../users")

        assert not request.called
