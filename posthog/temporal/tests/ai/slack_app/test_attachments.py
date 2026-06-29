from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.temporal.ai.slack_app.attachments import build_slack_attachment_prompt_text, prepare_slack_file_artifacts


def _slack_file(**overrides: object) -> dict[str, object]:
    file: dict[str, object] = {
        "id": "F123",
        "name": "debug.log",
        "mimetype": "text/plain",
        "filetype": "text",
        "size": 12,
        "url_private_download": "https://files.slack.com/files-pri/T123-F123/debug.log",
    }
    file.update(overrides)
    return file


class TestSlackAttachments(SimpleTestCase):
    def test_prepares_safe_slack_file_as_user_attachment(self) -> None:
        with patch("posthog.temporal.ai.slack_app.attachments._download_slack_file", return_value=b"hello") as download:
            prepared = prepare_slack_file_artifacts([_slack_file()], "xoxb-token")

        download.assert_called_once_with("https://files.slack.com/files-pri/T123-F123/debug.log", "xoxb-token")
        assert prepared.requested_count == 1
        assert prepared.skipped_messages == []
        assert prepared.artifacts == [
            {
                "name": "debug.log",
                "type": "user_attachment",
                "source": "slack_user_attachment",
                "content_type": "text/plain",
                "content_bytes": b"hello",
            }
        ]

    def test_blocks_dangerous_attachment_metadata_without_downloading(self) -> None:
        with patch("posthog.temporal.ai.slack_app.attachments._download_slack_file") as download:
            prepared = prepare_slack_file_artifacts(
                [
                    _slack_file(name="installer.exe", mimetype="application/x-msdownload"),
                    _slack_file(name="deploy.sh", mimetype="text/plain", filetype="shell"),
                ],
                "xoxb-token",
            )

        download.assert_not_called()
        assert prepared.artifacts == []
        assert prepared.skipped_messages == [
            "installer.exe was skipped because executable or script attachments are not allowed.",
            "deploy.sh was skipped because executable or script attachments are not allowed.",
        ]

    def test_blocks_script_payload_after_download(self) -> None:
        with patch(
            "posthog.temporal.ai.slack_app.attachments._download_slack_file",
            return_value=b"#!/bin/sh\necho unsafe\n",
        ):
            prepared = prepare_slack_file_artifacts([_slack_file(name="notes.txt")], "xoxb-token")

        assert prepared.artifacts == []
        assert prepared.skipped_messages == [
            "notes.txt was skipped because executable or script attachments are not allowed."
        ]

    def test_rejects_non_slack_download_url(self) -> None:
        with patch("posthog.temporal.ai.slack_app.attachments._download_slack_file") as download:
            prepared = prepare_slack_file_artifacts(
                [_slack_file(url_private_download="https://example.com/debug.log")],
                "xoxb-token",
            )

        download.assert_not_called()
        assert prepared.artifacts == []
        assert prepared.skipped_messages == ["debug.log was skipped because its download URL was not a Slack file URL."]

    def test_build_prompt_handles_file_only_message(self) -> None:
        prompt = build_slack_attachment_prompt_text(
            None,
            uploaded_artifacts=[{"name": "debug.log"}],
            skipped_messages=["deploy.sh was skipped because executable or script attachments are not allowed."],
        )

        assert prompt == (
            "Slack attachment(s) available to the agent as task files: debug.log.\n\n"
            "Slack attachment(s) skipped:\n"
            "- deploy.sh was skipped because executable or script attachments are not allowed."
        )
