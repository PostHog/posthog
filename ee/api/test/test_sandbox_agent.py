import json

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models import OrganizationMembership

from ee.api.sandbox_agent import (
    _extract_agent_logs,
    _extract_text_from_content,
    _format_tool_input,
    _format_tool_output,
)


class TestExtractTextFromContent(TestCase):
    @parameterized.expand(
        [
            ("dict_with_text", {"text": "hello world"}, "hello world"),
            ("dict_with_thinking", {"thinking": "reasoning here"}, "reasoning here"),
            ("dict_text_takes_precedence_over_thinking", {"text": "answer", "thinking": "thought"}, "answer"),
            ("dict_empty", {}, ""),
            ("dict_with_none_text", {"text": None, "thinking": None}, ""),
            ("dict_with_neither_key", {"type": "tool_use", "id": "abc"}, ""),
            ("string_input", "just a string", ""),
            ("none_input", None, ""),
            ("integer_input", 42, ""),
            (
                "list_of_text_blocks",
                [{"text": "first"}, {"text": "second"}],
                "first\nsecond",
            ),
            (
                "list_with_thinking_blocks",
                [{"thinking": "thought one"}, {"thinking": "thought two"}],
                "thought one\nthought two",
            ),
            (
                "list_mixed_blocks",
                [{"text": "visible"}, {"type": "tool_use"}, {"text": "also visible"}],
                "visible\nalso visible",
            ),
            ("list_empty", [], ""),
            (
                "list_with_empty_blocks",
                [{"text": ""}, {"thinking": ""}],
                "",
            ),
            (
                "list_with_non_dict_elements",
                ["string_element", {"text": "valid"}],
                "valid",
            ),
        ]
    )
    def test_extract_text(self, _name, content, expected):
        assert _extract_text_from_content(content) == expected


class TestFormatToolInput(TestCase):
    @parameterized.expand(
        [
            ("bash_returns_command", "Bash", {"command": "ls -la"}, "ls -la"),
            ("bash_missing_command", "Bash", {}, ""),
            ("read_returns_file_path", "Read", {"file_path": "/tmp/file.py"}, "/tmp/file.py"),
            ("grep_returns_pattern", "Grep", {"pattern": "def foo"}, "def foo"),
            ("glob_returns_path", "Glob", {"path": "**/*.ts"}, "**/*.ts"),
            ("grep_prefers_pattern_over_path", "Grep", {"pattern": "*.py", "path": "/src"}, "*.py"),
            ("write_returns_file_path", "Write", {"file_path": "/out/file.py"}, "/out/file.py"),
            ("edit_returns_file_path", "Edit", {"file_path": "/src/app.py"}, "/src/app.py"),
            (
                "agent_returns_truncated_prompt",
                "Agent",
                {"prompt": "A" * 250},
                "A" * 200,
            ),
            (
                "unknown_tool_returns_json",
                "UnknownTool",
                {"key": "value"},
                '{"key":"value"}',
            ),
            ("non_dict_input_returns_empty", "Bash", "not a dict", ""),
            ("non_dict_none_input_returns_empty", "Read", None, ""),
        ]
    )
    def test_format_input(self, _name, tool_name, raw_input, expected):
        assert _format_tool_input(tool_name, raw_input) == expected

    def test_unknown_tool_unserializable_input_returns_empty(self):
        raw_input = {"key": object()}
        result = _format_tool_input("CustomTool", raw_input)
        assert result == ""


class TestFormatToolOutput(TestCase):
    @parameterized.expand(
        [
            ("string_passthrough", "Bash", "output text", "output text"),
            ("empty_string_passthrough", "Read", "", ""),
            (
                "list_of_text_blocks",
                "Read",
                [{"text": "file contents"}],
                "file contents",
            ),
            (
                "list_multiple_text_blocks",
                "Grep",
                [{"text": "line one"}, {"text": "line two"}],
                "line one\nline two",
            ),
            (
                "list_blocks_skips_non_text",
                "Glob",
                [{"type": "tool_result"}, {"text": "actual result"}],
                "actual result",
            ),
            ("list_empty", "Bash", [], ""),
            (
                "dict_serialized_to_json",
                "UnknownTool",
                {"status": "ok", "count": 3},
                '{"status":"ok","count":3}',
            ),
            ("none_returns_empty", "Bash", None, ""),
            ("integer_returns_empty", "Bash", 42, ""),
        ]
    )
    def test_format_output(self, _name, tool_name, raw_output, expected):
        assert _format_tool_output(tool_name, raw_output) == expected

    def test_dict_unserializable_falls_back_to_str(self):
        class Unserializable:
            def __repr__(self):
                return "Unserializable()"

        raw_output = {"key": Unserializable()}
        result = _format_tool_output("Tool", raw_output)
        # Falls back to str() representation when JSON serialization fails
        assert "Unserializable" in result


def _jsonl(*notifications) -> str:
    lines = [json.dumps({"notification": n}) for n in notifications]
    return "\n".join(lines)


def _console(level, message):
    return {"method": "_posthog/console", "params": {"level": level, "message": message}}


def _session_update(session_update_type, **kwargs):
    update = {"sessionUpdate": session_update_type, **kwargs}
    return {"method": "session/update", "params": {"update": update}}


class TestExtractAgentLogs(TestCase):
    def _make_task_run(self, log_url="s3://bucket/logs.jsonl"):
        task_run = MagicMock()
        task_run.log_url = log_url
        return task_run

    def _run(self, raw_content, log_url="s3://bucket/logs.jsonl"):
        task_run = self._make_task_run(log_url)
        with patch("posthog.storage.object_storage.read", return_value=raw_content):
            return _extract_agent_logs(task_run)

    def test_returns_empty_list_when_storage_returns_none(self):
        result = self._run(None)
        assert result == []

    def test_returns_empty_list_when_storage_returns_empty_string(self):
        result = self._run("")
        assert result == []

    def test_returns_empty_list_when_storage_raises(self):
        task_run = self._make_task_run()
        with patch("posthog.storage.object_storage.read", side_effect=Exception("S3 error")):
            result = _extract_agent_logs(task_run)
        assert result == []

    def test_returns_empty_list_when_log_is_only_whitespace(self):
        result = self._run("   \n\n  ")
        assert result == []

    def test_skips_invalid_json_lines(self):
        content = "not json\n" + json.dumps({"notification": _console("info", "valid message")})
        result = self._run(content)
        assert result == ["[info] valid message"]

    def test_skips_lines_without_notification_key(self):
        content = json.dumps({"other_key": "value"})
        result = self._run(content)
        assert result == []

    def test_skips_lines_where_notification_is_not_dict(self):
        content = json.dumps({"notification": "string_not_dict"})
        result = self._run(content)
        assert result == []

    def test_console_info_message_extracted(self):
        content = _jsonl(_console("info", "starting up"))
        result = self._run(content)
        assert result == ["[info] starting up"]

    def test_console_error_message_extracted(self):
        content = _jsonl(_console("error", "something went wrong"))
        result = self._run(content)
        assert result == ["[error] something went wrong"]

    def test_console_empty_message_skipped(self):
        content = _jsonl(_console("info", ""))
        result = self._run(content)
        assert result == []

    def test_multiple_console_messages_all_extracted(self):
        content = _jsonl(
            _console("info", "first"),
            _console("warn", "second"),
        )
        result = self._run(content)
        assert result == ["[info] first", "[warn] second"]

    def test_thought_chunks_concatenated_and_flushed(self):
        content = _jsonl(
            _session_update("agent_thought_chunk", content={"text": "part one "}),
            _session_update("agent_thought_chunk", content={"text": "part two"}),
            _session_update("agent_message", content={"text": "final answer"}),
        )
        result = self._run(content)
        assert result == ["Thinking: part one part two", "Agent: final answer"]

    def test_thought_chunk_flushed_before_console_message(self):
        content = _jsonl(
            _session_update("agent_thought_chunk", content={"text": "some thought"}),
            _console("info", "console msg"),
        )
        result = self._run(content)
        assert result == ["Thinking: some thought", "[info] console msg"]

    def test_empty_thought_chunks_produce_no_thinking_entry(self):
        content = _jsonl(
            _session_update("agent_thought_chunk", content={"text": ""}),
            _session_update("agent_message", content={"text": "answer"}),
        )
        result = self._run(content)
        assert result == ["Agent: answer"]

    def test_agent_message_extracted(self):
        content = _jsonl(_session_update("agent_message", content={"text": "Here is your answer"}))
        result = self._run(content)
        assert result == ["Agent: Here is your answer"]

    def test_agent_message_chunk_concatenated(self):
        content = _jsonl(
            _session_update("agent_message_chunk", content={"text": "Hello "}),
            _session_update("agent_message_chunk", content={"text": "world"}),
        )
        result = self._run(content)
        assert result == ["Agent: Hello world"]

    def test_agent_message_flushed_before_thought_chunk(self):
        content = _jsonl(
            _session_update("agent_message_chunk", content={"text": "response text"}),
            _session_update("agent_thought_chunk", content={"text": "new thought"}),
        )
        result = self._run(content)
        assert result == ["Agent: response text", "Thinking: new thought"]

    def test_tool_call_without_input_summary(self):
        content = _jsonl(
            _session_update(
                "tool_call",
                toolCallId="id-1",
                _meta={"claudeCode": {"toolName": "SomeTool"}},
            )
        )
        result = self._run(content)
        assert result == ["Tool: SomeTool"]

    def test_tool_call_with_bash_command(self):
        content = _jsonl(
            _session_update(
                "tool_call",
                toolCallId="id-2",
                _meta={"claudeCode": {"toolName": "Bash"}},
                rawInput={"command": "git status"},
            )
        )
        result = self._run(content)
        assert result == ["Tool: Bash — git status"]

    def test_tool_call_flushes_pending_message_buffer(self):
        content = _jsonl(
            _session_update("agent_message_chunk", content={"text": "pending message"}),
            _session_update(
                "tool_call",
                toolCallId="id-3",
                _meta={"claudeCode": {"toolName": "Read"}},
                rawInput={"file_path": "/tmp/file.py"},
            ),
        )
        result = self._run(content)
        assert result == ["Agent: pending message", "Tool: Read — /tmp/file.py"]

    def test_tool_call_update_completed_logs_result(self):
        content = _jsonl(
            _session_update(
                "tool_call",
                toolCallId="id-4",
                _meta={"claudeCode": {"toolName": "Bash"}},
                rawInput={"command": "ls"},
            ),
            _session_update(
                "tool_call_update",
                toolCallId="id-4",
                status="completed",
                rawOutput="file1.py\nfile2.py",
                _meta={"claudeCode": {"toolName": "Bash"}},
            ),
        )
        result = self._run(content)
        assert result == ["Tool: Bash — ls", "  Result: file1.py\nfile2.py"]

    def test_tool_call_update_failed_logs_error(self):
        content = _jsonl(
            _session_update(
                "tool_call",
                toolCallId="id-5",
                _meta={"claudeCode": {"toolName": "Bash"}},
                rawInput={"command": "bad-cmd"},
            ),
            _session_update(
                "tool_call_update",
                toolCallId="id-5",
                status="failed",
                rawOutput="command not found",
                _meta={"claudeCode": {"toolName": "Bash"}},
            ),
        )
        result = self._run(content)
        assert result == ["Tool: Bash — bad-cmd", "  Error: command not found"]

    def test_tool_call_update_without_prior_tool_call_logs_invocation(self):
        content = _jsonl(
            _session_update(
                "tool_call_update",
                toolCallId="id-new",
                status="completed",
                rawOutput="done",
                _meta={"claudeCode": {"toolName": "Bash"}},
                rawInput={"command": "echo hi"},
            )
        )
        result = self._run(content)
        assert "Tool: Bash — echo hi" in result
        assert "  Result: done" in result

    def test_tool_call_update_in_progress_does_not_log_result(self):
        content = _jsonl(
            _session_update(
                "tool_call",
                toolCallId="id-6",
                _meta={"claudeCode": {"toolName": "Bash"}},
                rawInput={"command": "sleep 1"},
            ),
            _session_update(
                "tool_call_update",
                toolCallId="id-6",
                status="in_progress",
                _meta={"claudeCode": {"toolName": "Bash"}},
            ),
        )
        result = self._run(content)
        assert result == ["Tool: Bash — sleep 1"]

    def test_tool_call_update_no_duplicate_invocation_when_already_seen(self):
        content = _jsonl(
            _session_update(
                "tool_call",
                toolCallId="id-7",
                _meta={"claudeCode": {"toolName": "Read"}},
                rawInput={"file_path": "/readme.md"},
            ),
            _session_update(
                "tool_call_update",
                toolCallId="id-7",
                status="completed",
                rawOutput="# Readme",
                _meta={"claudeCode": {"toolName": "Read"}},
                rawInput={"file_path": "/readme.md"},
            ),
        )
        result = self._run(content)
        tool_entries = [m for m in result if m.startswith("Tool:")]
        assert len(tool_entries) == 1

    def test_long_thinking_text_truncated_to_max_length(self):
        long_text = "x" * 600
        content = _jsonl(_session_update("agent_thought_chunk", content={"text": long_text}))
        result = self._run(content)
        assert len(result) == 1
        assert result[0].startswith("Thinking: ")
        assert len(result[0]) <= len("Thinking: ") + 500

    def test_long_agent_message_truncated_to_max_length(self):
        long_text = "y" * 600
        content = _jsonl(_session_update("agent_message", content={"text": long_text}))
        result = self._run(content)
        assert len(result) == 1
        assert result[0].startswith("Agent: ")
        assert len(result[0]) <= len("Agent: ") + 500

    def test_remaining_buffers_flushed_at_end_of_log(self):
        content = _jsonl(_session_update("agent_message_chunk", content={"text": "trailing response"}))
        result = self._run(content)
        assert result == ["Agent: trailing response"]

    def test_unknown_session_update_type_ignored(self):
        content = _jsonl(_session_update("unknown_event_type", content={"text": "ignored"}))
        result = self._run(content)
        assert result == []

    def test_non_session_update_method_ignored(self):
        content = _jsonl({"method": "some/other/method", "params": {"data": "ignored"}})
        result = self._run(content)
        assert result == []

    def test_mixed_log_with_multiple_entry_types(self):
        content = _jsonl(
            _console("info", "agent started"),
            _session_update("agent_thought_chunk", content={"text": "let me think"}),
            _session_update("agent_message", content={"text": "I will run a command"}),
            _session_update(
                "tool_call",
                toolCallId="id-mix",
                _meta={"claudeCode": {"toolName": "Bash"}},
                rawInput={"command": "echo hello"},
            ),
            _session_update(
                "tool_call_update",
                toolCallId="id-mix",
                status="completed",
                rawOutput="hello",
                _meta={"claudeCode": {"toolName": "Bash"}},
            ),
            _session_update("agent_message", content={"text": "Done!"}),
        )
        result = self._run(content)
        assert result == [
            "[info] agent started",
            "Thinking: let me think",
            "Agent: I will run a command",
            "Tool: Bash — echo hello",
            "  Result: hello",
            "Agent: Done!",
        ]


class TestAgentRunView(BaseTest):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def test_run_requires_auth(self):
        response = self.client.post(
            "/agent/run",
            data={"message": "How many users?"},
            format="json",
        )
        assert response.status_code == 401

    def test_run_rejects_invalid_token(self):
        response = self.client.post(
            "/agent/run",
            data={"message": "How many users?"},
            format="json",
            HTTP_AUTHORIZATION="Bearer invalid-token",
        )
        assert response.status_code == 401

    def test_run_requires_message(self):
        response = self.client.post(
            "/agent/run",
            data={},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.team.api_token}",
        )
        assert response.status_code == 400
