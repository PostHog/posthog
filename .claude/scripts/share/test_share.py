#!/usr/bin/env python3
"""Tests for share.py script."""

import json
import tempfile
import subprocess
from pathlib import Path

import unittest
from unittest.mock import MagicMock, patch

# Import the share module
import share as share_session


class TestGetProjectSlug(unittest.TestCase):
    @patch("share.Path.cwd")
    def test_converts_path_to_slug(self, mock_cwd):
        mock_cwd.return_value = Path("/Users/test/projects/my-project")
        result = share_session.get_project_slug()
        assert result == "Users-test-projects-my-project"

    @patch("share.Path.cwd")
    def test_strips_leading_dash(self, mock_cwd):
        mock_cwd.return_value = Path("/simple")
        result = share_session.get_project_slug()
        assert result == "simple"


class TestFindLatestSessionLog(unittest.TestCase):
    @patch("share.Path.home")
    def test_finds_most_recent_log(self, mock_home):
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
            assert result == new_log

    @patch("share.Path.home")
    def test_exits_when_no_logs_directory(self, mock_home):
        with tempfile.TemporaryDirectory() as temp_dir:
            mock_home.return_value = Path(temp_dir)

            with self.assertRaises(SystemExit):
                share_session.find_latest_session_log("nonexistent-project")

    @patch("share.Path.home")
    def test_exits_when_no_log_files(self, mock_home):
        with tempfile.TemporaryDirectory() as temp_dir:
            logs_dir = Path(temp_dir) / ".claude" / "projects" / "-empty-project"
            logs_dir.mkdir(parents=True)
            mock_home.return_value = Path(temp_dir)

            with self.assertRaises(SystemExit):
                share_session.find_latest_session_log("empty-project")


class TestParseSessionLog(unittest.TestCase):
    def test_parses_user_message(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            json.dump({"type": "user", "message": {"content": "Hello"}}, f)
            f.write("\n")
            f.flush()

            result = share_session.parse_session_log(f.name)
            assert result == [{"type": "user", "content": "Hello"}]

            Path(f.name).unlink()

    def test_parses_assistant_text_message(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            json.dump(
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi there"}]}},
                f,
            )
            f.write("\n")
            f.flush()

            result = share_session.parse_session_log(f.name)
            assert result == [{"type": "assistant", "content": "Hi there"}]

            Path(f.name).unlink()

    def test_parses_tool_use(self):
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
            assert result == [{"type": "tool_use", "name": "bash", "input": {"command": "ls"}}]

            Path(f.name).unlink()

    def test_skips_invalid_json_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("invalid json\n")
            json.dump({"type": "user", "message": {"content": "Valid"}}, f)
            f.write("\n")
            f.flush()

            result = share_session.parse_session_log(f.name)
            assert result == [{"type": "user", "content": "Valid"}]

            Path(f.name).unlink()


class TestGenerateMarkdown(unittest.TestCase):
    def test_generates_header_with_metadata(self):
        messages = []
        result = share_session.generate_markdown(messages, "2025-10-15", "Test session")

        assert "# Claude Code Session" in result
        assert "**Date**: 2025-10-15" in result
        assert "**Description**: Test session" in result

    def test_generates_user_message(self):
        messages = [{"type": "user", "content": "Hello"}]
        result = share_session.generate_markdown(messages, "2025-10-15", "Test")

        assert "## User" in result
        assert "Hello" in result

    def test_generates_assistant_message(self):
        messages = [{"type": "assistant", "content": "Hi there"}]
        result = share_session.generate_markdown(messages, "2025-10-15", "Test")

        assert "## Assistant" in result
        assert "Hi there" in result

    def test_generates_tool_use_with_collapsible_details(self):
        messages = [{"type": "tool_use", "name": "bash", "input": {"command": "ls"}}]
        result = share_session.generate_markdown(messages, "2025-10-15", "Test")

        assert "<details>" in result
        assert "<code>bash</code>" in result
        assert "```json" in result
        assert '"command": "ls"' in result
        assert "</details>" in result


class TestSanitizeDescription(unittest.TestCase):
    def test_replaces_spaces_with_dashes(self):
        result = share_session.sanitize_description("hello world")
        assert result == "hello-world"

    def test_removes_special_characters(self):
        result = share_session.sanitize_description("test!@#$%")
        assert result == "test"

    def test_keeps_alphanumeric_and_dashes(self):
        result = share_session.sanitize_description("test-123-abc")
        assert result == "test-123-abc"

    def test_truncates_to_50_characters(self):
        long_desc = "a" * 100
        result = share_session.sanitize_description(long_desc)
        assert len(result) == 50


class TestGetGithubUsername(unittest.TestCase):
    @patch("share.subprocess.run")
    def test_returns_username_from_gh_cli(self, mock_run):
        mock_run.return_value = MagicMock(stdout="testuser\n")
        result = share_session.get_github_username()
        assert result == "testuser"

    @patch("share.subprocess.run")
    def test_exits_on_gh_cli_error(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "gh")
        with self.assertRaises(SystemExit):
            share_session.get_github_username()


class TestShareSession(unittest.TestCase):
    @patch("share.subprocess.run")
    @patch("share.tempfile.TemporaryDirectory")
    def test_creates_session_file_in_user_directory(self, mock_temp, mock_run):
        with tempfile.TemporaryDirectory() as real_temp:
            mock_temp.return_value.__enter__.return_value = real_temp

            share_session.share_session("# Test", "test-session", "testuser")

            expected_path = Path(real_temp) / "claude-sessions" / "sessions" / "testuser"
            assert expected_path.exists()

    @patch("share.subprocess.run")
    @patch("share.tempfile.TemporaryDirectory")
    def test_returns_github_url(self, mock_temp, mock_run):
        with tempfile.TemporaryDirectory() as real_temp:
            mock_temp.return_value.__enter__.return_value = real_temp

            result = share_session.share_session("# Test", "test-session", "testuser")

            assert result.startswith("https://github.com/PostHog/claude-sessions/blob/main/sessions/testuser/")
            assert result.endswith("-test-session.md")

    @patch("share.subprocess.run")
    @patch("share.tempfile.TemporaryDirectory")
    def test_exits_on_clone_failure(self, mock_temp, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "gh")

        with self.assertRaises(SystemExit):
            share_session.share_session("# Test", "test-session", "testuser")


if __name__ == "__main__":
    unittest.main()
