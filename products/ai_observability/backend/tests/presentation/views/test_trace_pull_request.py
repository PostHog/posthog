from typing import TYPE_CHECKING

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.engineering_analytics.backend.facade import api as engineering_analytics_api
from products.engineering_analytics.backend.facade.contracts import ENGINEERING_ANALYTICS_FEATURE_FLAG, BranchPRMatch

from .trace_fixtures import T0, create_trace, encode_segment

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse


PULL_REQUEST_MATCH = BranchPRMatch(repo="acme/app", number=42, title="Answer billing questions", state="open")


class TestTracePullRequestView(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        create_trace(self.team, extra_properties={"$ai_git_branch": "feat/rag", "$ai_git_repo": "acme/app"})

    def _get(
        self, segment: str = encode_segment("trace-1"), *, flag: bool = True, headers: dict[str, str] | None = None
    ) -> tuple["_MonkeyPatchedResponse", MagicMock]:
        def only_engineering_analytics(key: str, *args: object, **kwargs: object) -> bool:
            return flag and key == ENGINEERING_ANALYTICS_FEATURE_FLAG

        with (
            patch("posthoganalytics.feature_enabled", side_effect=only_engineering_analytics),
            patch.object(engineering_analytics_api, "resolve_branch", return_value=[PULL_REQUEST_MATCH]) as resolve,
        ):
            response = self.client.get(
                f"/api/projects/{self.team.id}/ai_observability/traces/{segment}/pull_request/",
                {"timestamp_hint": T0.isoformat()},
                headers=headers or {},
            )
        return response, resolve

    def test_returns_the_pull_request_in_camel_case(self) -> None:
        response, _resolve = self._get()

        assert (response.status_code, response.json()) == (
            200,
            {
                "pullRequest": {
                    "repoOwner": "acme",
                    "repoName": "app",
                    "number": 42,
                    "title": "Answer billing questions",
                }
            },
        )

    def test_requires_the_engineering_analytics_flag(self) -> None:
        response, resolve = self._get(flag=False)

        assert (response.status_code, resolve.called) == (403, False)

    @parameterized.expand([(["llm_analytics:read"], 403), (["llm_analytics:read", "engineering_analytics:read"], 200)])
    def test_an_api_key_needs_both_scopes(self, scopes: list[str], expected_status: int) -> None:
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()

        response, _resolve = self._get(headers={"authorization": f"Bearer {key}"})

        assert response.status_code == expected_status, response.content

    def test_rejects_an_unencoded_trace_id(self) -> None:
        response, resolve = self._get("trace-1")

        assert (response.status_code, resolve.called) == (400, False)
