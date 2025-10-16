#!/usr/bin/env python3
"""Tests for share.py script."""

import json
import tempfile
import subprocess
from pathlib import Path

import unittest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

# Import the share module
import share as share_session


class TestGetProjectSlug(unittest.TestCase):
    @patch("share.Path.cwd")
    def test_converts_path_to_slug(self, mock_cwd) -> None:
        mock_cwd.return_value = Path("/Users/test/projects/my-project")
        result = share_session.get_project_slug()
        self.assertEqual(result, "Users-test-projects-my-project")

    @patch("share.Path.cwd")
    def test_strips_leading_dash(self, mock_cwd) -> None:
        mock_cwd.return_value = Path("/simple")
        result = share_session.get_project_slug()
        self.assertEqual(result, "simple")


class TestFindLatestSessionLog(unittest.TestCase):
    @patch("share.Path.home")
    def test_finds_most_recent_log(self, mock_home) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs_dir = Path(temp_dir) / ".claude" / "projects" / "-test-project"
            logs_dir.mkdir(parents=True)

            # Create log files with different timestamps
            old_log = logs_dir / "old.jsonl"
            old_log.touch()
            old_log.write_text("old")

            new_log = logs_dir / "new.jsonl"
            new_log.touch()
            new_log.write_text("new")

            mock_home.return_value = Path(temp_dir)

            result = share_session.find_latest_session_log("test-project")
            self.assertEqual(result, new_log)

    @patch("share.Path.home")
    def test_exits_when_no_logs_directory(self, mock_home) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mock_home.return_value = Path(temp_dir)

            with self.assertRaises(SystemExit):
                share_session.find_latest_session_log("nonexistent-project")

    @patch("share.Path.home")
    def test_exits_when_no_log_files(self, mock_home) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs_dir = Path(temp_dir) / ".claude" / "projects" / "-empty-project"
            logs_dir.mkdir(parents=True)
            mock_home.return_value = Path(temp_dir)

            with self.assertRaises(SystemExit):
                share_session.find_latest_session_log("empty-project")


class TestParseSessionLog(unittest.TestCase):
    def test_parses_user_message(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            json.dump({"type": "user", "message": {"content": "Hello"}}, f)
            f.write("\n")
            f.flush()

            result = share_session.parse_session_log(f.name)
            self.assertEqual(result, [{"type": "user", "content": "Hello"}])

            Path(f.name).unlink()

    def test_parses_assistant_text_message(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            json.dump(
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi there"}]}},
                f,
            )
            f.write("\n")
            f.flush()

            result = share_session.parse_session_log(f.name)
            self.assertEqual(result, [{"type": "assistant", "content": "Hi there"}])

            Path(f.name).unlink()

    def test_parses_tool_use(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            json.dump(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "bash", "input": {"command": "ls"}}]},
                },
                f,
            )
            f.write("\n")
            f.flush()

            result = share_session.parse_session_log(f.name)
            self.assertEqual(result, [{"type": "tool_use", "name": "bash", "input": {"command": "ls"}}])

            Path(f.name).unlink()

    def test_skips_invalid_json_lines(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("invalid json\n")
            json.dump({"type": "user", "message": {"content": "Valid"}}, f)
            f.write("\n")
            f.flush()

            result = share_session.parse_session_log(f.name)
            self.assertEqual(result, [{"type": "user", "content": "Valid"}])

            Path(f.name).unlink()


class TestGenerateMarkdown(unittest.TestCase):
    def test_generates_header_with_metadata(self) -> None:
        messages = []
        result = share_session.generate_markdown(messages, "2025-10-15", "Test session")

        self.assertIn("# Claude Code Session", result)
        self.assertIn("**Date**: 2025-10-15", result)
        self.assertIn("**Description**: Test session", result)

    def test_generates_user_message(self) -> None:
        messages = [{"type": "user", "content": "Hello"}]
        result = share_session.generate_markdown(messages, "2025-10-15", "Test")

        self.assertIn("## User", result)
        self.assertIn("Hello", result)

    def test_generates_assistant_message(self) -> None:
        messages = [{"type": "assistant", "content": "Hi there"}]
        result = share_session.generate_markdown(messages, "2025-10-15", "Test")

        self.assertIn("## Assistant", result)
        self.assertIn("Hi there", result)

    def test_generates_tool_use_with_collapsible_details(self) -> None:
        messages = [{"type": "tool_use", "name": "bash", "input": {"command": "ls"}}]
        result = share_session.generate_markdown(messages, "2025-10-15", "Test")

        self.assertIn("<details>", result)
        self.assertIn("<code>bash</code>", result)
        self.assertIn("```json", result)
        self.assertIn('"command": "ls"', result)
        self.assertIn("</details>", result)


class TestSanitizeDescription(unittest.TestCase):
    @parameterized.expand(
        [
            ("replaces_spaces_with_dashes", "hello world", "hello-world"),
            ("removes_special_characters", "test!@#$%", "test"),
            ("keeps_alphanumeric_and_dashes", "test-123-abc", "test-123-abc"),
        ]
    )
    def test_sanitize_description(self, name: str, input_desc: str, expected: str) -> None:
        result = share_session.sanitize_description(input_desc)
        self.assertEqual(result, expected)

    def test_truncates_to_50_characters(self) -> None:
        long_desc = "a" * 100
        result = share_session.sanitize_description(long_desc)
        self.assertEqual(len(result), 50)


class TestGetGithubUsername(unittest.TestCase):
    @patch("share.subprocess.run")
    def test_returns_username_from_gh_cli(self, mock_run) -> None:
        mock_run.return_value = MagicMock(stdout="testuser\n")
        result = share_session.get_github_username()
        self.assertEqual(result, "testuser")

    @patch("share.subprocess.run")
    def test_exits_on_gh_cli_error(self, mock_run) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "gh")
        with self.assertRaises(SystemExit):
            share_session.get_github_username()


class TestShareSession(unittest.TestCase):
    @patch("share.subprocess.run")
    @patch("share.tempfile.TemporaryDirectory")
    def test_creates_session_file_in_user_directory(self, mock_temp, mock_run) -> None:
        with tempfile.TemporaryDirectory() as real_temp:
            mock_temp.return_value.__enter__.return_value = real_temp

            share_session.share_session("# Test", "test-session", "testuser")

            expected_path = Path(real_temp) / "claude-sessions" / "sessions" / "testuser"
            self.assertTrue(expected_path.exists())

    @patch("share.subprocess.run")
    @patch("share.tempfile.TemporaryDirectory")
    def test_returns_github_url(self, mock_temp, mock_run) -> None:
        with tempfile.TemporaryDirectory() as real_temp:
            mock_temp.return_value.__enter__.return_value = real_temp

            result = share_session.share_session("# Test", "test-session", "testuser")

            self.assertTrue(
                result.startswith("https://github.com/PostHog/claude-sessions/blob/main/sessions/testuser/")
            )
            self.assertTrue(result.endswith("-test-session.md"))

    @patch("share.subprocess.run")
    @patch("share.tempfile.TemporaryDirectory")
    def test_exits_on_clone_failure(self, mock_temp, mock_run) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "gh")

        with self.assertRaises(SystemExit):
            share_session.share_session("# Test", "test-session", "testuser")


if __name__ == "__main__":
    unittest.main()
