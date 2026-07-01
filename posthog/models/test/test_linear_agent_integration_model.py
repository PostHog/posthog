from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.models.integration import Integration, LinearAgentIntegration

ORG = "org-1"
BOT = "bot-1"


class TestLinearAgentIntegrationModel(BaseTest):
    def _create_integration(self) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="linear-agent",
            integration_id=ORG,
            config={"data": {"viewer": {"id": BOT, "organization": {"id": ORG, "urlKey": "acme"}}}},
            sensitive_config={"access_token": "tok", "refresh_token": "ref"},
        )

    def test_execute_refreshes_and_retries_once_on_401(self):
        agent = LinearAgentIntegration(self._create_integration())
        unauthorized = MagicMock(status_code=401)
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"data": {"viewer": {"id": BOT}}}

        with (
            patch("posthog.models.integration.requests.post", side_effect=[unauthorized, ok]) as mock_post,
            patch("posthog.models.integration.OauthIntegration.refresh_access_token") as mock_refresh,
        ):
            result = agent.execute("{ viewer { id } }")

        self.assertEqual(mock_post.call_count, 2)
        mock_refresh.assert_called_once()
        self.assertEqual(result, {"data": {"viewer": {"id": BOT}}})

    def test_execute_raises_on_graphql_errors(self):
        agent = LinearAgentIntegration(self._create_integration())
        errored = MagicMock(status_code=200)
        errored.json.return_value = {"errors": [{"message": "Field 'foo' doesn't exist"}]}

        with patch("posthog.models.integration.requests.post", return_value=errored):
            with self.assertRaises(Exception):
                agent.execute("{ foo }")

    def test_create_comment_passes_issue_and_body_as_variables(self):
        agent = LinearAgentIntegration(self._create_integration())
        with patch.object(
            agent, "execute", return_value={"data": {"commentCreate": {"comment": {"id": "comment-1"}}}}
        ) as mock_execute:
            comment_id = agent.create_comment("issue-uuid", "PR opened: https://example.com/pr/1")

        self.assertEqual(comment_id, "comment-1")
        query = mock_execute.call_args.args[0]
        variables = mock_execute.call_args.kwargs["variables"]
        self.assertIn("commentCreate", query)
        self.assertEqual(variables, {"issueId": "issue-uuid", "body": "PR opened: https://example.com/pr/1"})
