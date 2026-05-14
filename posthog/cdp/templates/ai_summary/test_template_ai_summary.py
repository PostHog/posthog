import pytest

from posthog.cdp.templates.ai_summary.template_ai_summary import template as template_ai_summary
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest

from common.hogvm.python.utils import UncaughtHogVMException


class TestTemplateAiSummary(BaseHogFunctionTemplateTest):
    template = template_ai_summary

    def _inputs(self, **kwargs):
        inputs = {
            "posthog_host": "https://us.posthog.com",
            "posthog_api_key": "phx_test_personal_api_key",
            "query": "SELECT count() FROM events WHERE timestamp >= now() - INTERVAL 1 HOUR",
            "anthropic_api_key": "sk-ant-test",
            "anthropic_model": "claude-sonnet-4-5",
            "max_tokens": 2000,
            "system_prompt": "You are a concise product analyst.",
            "user_prompt": "Here is the latest data:\n\n{query_result}\n\nWrite the summary.",
            "slack_workspace": {"access_token": "xoxb-test"},
            "slack_channel": "C0B3E1Y576X",
        }
        inputs.update(kwargs)
        return inputs

    def _mock_fetch_three_stage(self, query_results=None, summary_text="The numbers are stable."):
        query_results = query_results if query_results is not None else [[42]]

        def responder(url, *_args):
            if "/api/projects/" in url and url.endswith("/query/"):
                return {"status": 200, "body": {"results": query_results}}
            if url == "https://api.anthropic.com/v1/messages":
                return {"status": 200, "body": {"content": [{"type": "text", "text": summary_text}]}}
            if url == "https://slack.com/api/chat.postMessage":
                return {"status": 200, "body": {"ok": True}}
            return {"status": 404, "body": {}}

        return responder

    def test_calls_query_anthropic_and_slack_in_order(self):
        self.mock_fetch_response = self._mock_fetch_three_stage(query_results=[[1234]])  # type: ignore
        res = self.run_function(self._inputs())

        assert res.result is None
        calls = self.get_mock_fetch_calls()
        assert len(calls) == 3
        assert calls[0][0] == "https://us.posthog.com/api/projects/1/query/"
        assert calls[1][0] == "https://api.anthropic.com/v1/messages"
        assert calls[2][0] == "https://slack.com/api/chat.postMessage"

    def test_query_request_uses_personal_api_key_and_hogql_kind(self):
        self.mock_fetch_response = self._mock_fetch_three_stage()  # type: ignore
        self.run_function(self._inputs())

        _url, query_opts = self.get_mock_fetch_calls()[0]
        assert query_opts["method"] == "POST"
        assert query_opts["headers"]["Authorization"] == "Bearer phx_test_personal_api_key"
        assert query_opts["body"]["query"]["kind"] == "HogQLQuery"
        assert "SELECT count()" in query_opts["body"]["query"]["query"]

    def test_anthropic_request_carries_model_and_substituted_prompt(self):
        self.mock_fetch_response = self._mock_fetch_three_stage(query_results=[["sample-intent-string"]])  # type: ignore
        self.run_function(
            self._inputs(
                anthropic_model="claude-opus-4-5",
                max_tokens=1500,
                system_prompt="Be terse.",
                user_prompt="Summarize: {query_result}",
            )
        )

        _url, llm_opts = self.get_mock_fetch_calls()[1]
        assert llm_opts["headers"]["x-api-key"] == "sk-ant-test"
        assert llm_opts["headers"]["anthropic-version"] == "2023-06-01"
        assert llm_opts["body"]["model"] == "claude-opus-4-5"
        assert llm_opts["body"]["max_tokens"] == 1500
        assert llm_opts["body"]["system"] == "Be terse."
        user_content = llm_opts["body"]["messages"][0]["content"]
        assert "Summarize:" in user_content
        assert "sample-intent-string" in user_content
        assert "{query_result}" not in user_content

    def test_slack_post_uses_summary_text_as_body(self):
        self.mock_fetch_response = self._mock_fetch_three_stage(summary_text="*Headline:* 1234 calls this hour.")  # type: ignore
        self.run_function(self._inputs())

        _url, slack_opts = self.get_mock_fetch_calls()[2]
        assert slack_opts["body"]["channel"] == "C0B3E1Y576X"
        assert slack_opts["body"]["text"] == "*Headline:* 1234 calls this hour."
        assert slack_opts["body"]["blocks"][0]["text"]["text"] == "*Headline:* 1234 calls this hour."
        assert slack_opts["headers"]["Authorization"] == "Bearer xoxb-test"

    def test_raises_when_query_api_returns_error_status(self):
        def responder(url, *_args):
            if "/query/" in url:
                return {"status": 401, "body": {"detail": "Invalid API key"}}
            return {"status": 200, "body": {}}

        self.mock_fetch_response = responder  # type: ignore
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(self._inputs())

        assert "HogQL query failed: 401" in e.value.message

    def test_raises_when_anthropic_returns_error_status(self):
        def responder(url, *_args):
            if "/query/" in url:
                return {"status": 200, "body": {"results": [[1]]}}
            if "anthropic.com" in url:
                return {"status": 529, "body": {"error": "overloaded"}}
            return {"status": 200, "body": {}}

        self.mock_fetch_response = responder  # type: ignore
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(self._inputs())

        assert "Anthropic call failed: 529" in e.value.message

    def test_raises_when_slack_returns_not_ok(self):
        def responder(url, *_args):
            if "/query/" in url:
                return {"status": 200, "body": {"results": [[1]]}}
            if "anthropic.com" in url:
                return {"status": 200, "body": {"content": [{"type": "text", "text": "summary"}]}}
            return {"status": 200, "body": {"ok": False, "error": "channel_not_found"}}

        self.mock_fetch_response = responder  # type: ignore

        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(self._inputs())

        assert "Slack post failed" in e.value.message
