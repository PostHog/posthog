import base64
from typing import Any

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration, GitHubIntegrationError, Integration
from posthog.models.integration.github_code_search import ExactCodeMatch, GitHubExactCodeSearch


def _github(account_type: str = "Organization") -> GitHubIntegration:
    integration = Integration(
        kind="github",
        integration_id="42",
        config={"account": {"name": "acme", "type": account_type}},
        sensitive_config={"access_token": "ACCESS_TOKEN"},
    )
    return GitHubIntegration(integration, source="test", priority=Priority.BATCH)


def _search_item(repository: str, path: str) -> dict[str, Any]:
    return {"path": path, "repository": {"full_name": repository}}


def _contents(text: str, sha: str) -> MagicMock:
    encoded = text.encode()
    payload = {"sha": sha, "size": len(encoded), "encoding": "base64", "content": base64.b64encode(encoded).decode()}
    return MagicMock(status_code=200, json=MagicMock(return_value=payload))


class TestGitHubExactCodeSearch(SimpleTestCase):
    def _search(
        self,
        github: GitHubIntegration,
        literal: str,
        search_body: dict[str, Any],
        files: dict[str, MagicMock],
    ) -> tuple[Any, list[dict[str, Any]]]:
        requests_made: list[dict[str, Any]] = []

        def api_request(method: str, path: str, **kwargs: Any) -> MagicMock:
            requests_made.append({"path": path, **kwargs})
            if path == "/search/code":
                return MagicMock(status_code=200, json=MagicMock(return_value=search_body))
            return files[path]

        with patch.object(github, "api_request", side_effect=api_request):
            result = GitHubExactCodeSearch(github).find(literal)
        return result, requests_made

    def test_keeps_only_files_with_the_exact_literal(self) -> None:
        sender = "\n".join(
            [
                "import { posthog } from './posthog'",
                "// sends password reset mail",
                "await posthog.emails.send({",
                "  templateKey: 'password-reset',",
                "})",
                "const legacy = 'password-reset-v2'",
                'const other = "password-reset"',
            ]
        )
        near_misses = "\n".join(["PASSWORD-RESET", "password_reset", "password reset", "xpassword-reset"])
        result, requests_made = self._search(
            _github(),
            "password-reset",
            {
                "total_count": 2,
                "incomplete_results": False,
                "items": [_search_item("acme/web", "src/send.ts"), _search_item("acme/web", "docs/notes.md")],
            },
            {
                "/repos/acme/web/contents/src/send.ts": _contents(sender, "sha-send"),
                "/repos/acme/web/contents/docs/notes.md": _contents(near_misses, "sha-notes"),
            },
        )

        assert result.matches == [
            ExactCodeMatch(repository="acme/web", path="src/send.ts", blob_sha="sha-send", line_numbers=(4, 7))
        ]
        assert result.complete is True
        assert requests_made[0]["params"]["q"] == '"password-reset" org:acme'

    def test_scopes_a_personal_account_with_the_user_qualifier(self) -> None:
        _, requests_made = self._search(
            _github(account_type="User"), "welcome", {"total_count": 0, "incomplete_results": False, "items": []}, {}
        )

        assert requests_made[0]["params"]["q"] == '"welcome" user:acme'

    @parameterized.expand(
        [
            ("github_says_incomplete", {"total_count": 1, "incomplete_results": True}, 200),
            ("more_results_than_read", {"total_count": 5, "incomplete_results": False}, 200),
            ("candidate_gone", {"total_count": 1, "incomplete_results": False}, 404),
        ]
    )
    def test_reports_an_incomplete_search(self, _name: str, search_body: dict[str, Any], file_status: int) -> None:
        file_response = _contents("send('welcome')", "sha-1")
        file_response.status_code = file_status
        result, _ = self._search(
            _github(),
            "welcome",
            {**search_body, "items": [_search_item("acme/web", "a.py")]},
            {"/repos/acme/web/contents/a.py": file_response},
        )

        assert result.complete is False

    def test_raises_when_github_refuses_the_search(self) -> None:
        github = _github()
        with patch.object(github, "api_request", return_value=MagicMock(status_code=403, text="forbidden")):
            with self.assertRaises(GitHubIntegrationError):
                GitHubExactCodeSearch(github).find("welcome")
