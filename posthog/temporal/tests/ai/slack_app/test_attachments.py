from typing import Any

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.temporal.ai.slack_app.attachments import (
    MAX_SLACK_ATTACHMENTS_PER_THREAD,
    build_slack_attachment_prompt_text,
    prepare_slack_file_artifacts,
    prepare_slack_thread_file_artifacts,
)

_TYPE_SKIP_SUFFIX = (
    "was skipped because only image, PDF, and plain-text attachments (logs, markdown, CSV, JSON, YAML) are supported."
)


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
    @parameterized.expand(
        [
            ("declared_mimetype", "text/plain", "text", "text/plain"),
            # Slack falls back to octet-stream for safe uploads; it must stay neutral.
            ("octet_stream_fallback", "application/octet-stream", None, "application/octet-stream"),
        ]
    )
    def test_prepares_safe_slack_file_as_user_attachment(
        self, _name: str, mimetype: str, filetype: str | None, expected_content_type: str
    ) -> None:
        file = _slack_file(mimetype=mimetype, filetype=filetype)
        with patch("posthog.temporal.ai.slack_app.attachments._download_slack_file", return_value=b"hello") as download:
            prepared = prepare_slack_file_artifacts([file], "xoxb-token")
            prepared_again = prepare_slack_file_artifacts([file], "xoxb-token")

        download.assert_called_with("https://files.slack.com/files-pri/T123-F123/debug.log", "xoxb-token")
        assert prepared.requested_count == 1
        assert prepared.skipped_messages == []
        assert len(prepared.artifacts) == 1
        artifact = prepared.artifacts[0]
        assert artifact["name"] == "debug.log"
        assert artifact["type"] == "user_attachment"
        assert artifact["source"] == "slack_user_attachment"
        assert artifact["content_type"] == expected_content_type
        assert artifact["content_bytes"] == b"hello"
        # Retried preparation must produce the same artifact id so uploads upsert.
        assert artifact["id"]
        assert prepared_again.artifacts == prepared.artifacts

    @parameterized.expand(
        [
            ("installer.exe", "application/x-msdownload", None),
            ("deploy.sh", "text/plain", "shell"),
            # Shebang-less macOS script: extension is the only dangerous signal.
            ("run.command", "text/plain", None),
            ("report.docm", "application/vnd.ms-word.document.macroEnabled.12", None),
            ("page.html", "text/html", "html"),
            ("diagram.svg", "image/svg+xml", None),
            # Contradiction: allowed extension, disallowed mimetype — fail closed.
            ("notes.txt", "application/x-sh", None),
        ]
    )
    def test_rejects_disallowed_attachment_metadata_without_downloading(
        self, name: str, mimetype: str, filetype: str | None
    ) -> None:
        with patch("posthog.temporal.ai.slack_app.attachments._download_slack_file") as download:
            prepared = prepare_slack_file_artifacts(
                [_slack_file(name=name, mimetype=mimetype, filetype=filetype)],
                "xoxb-token",
            )

        download.assert_not_called()
        assert prepared.artifacts == []
        assert prepared.skipped_messages == [f"{name} {_TYPE_SKIP_SUFFIX}"]

    def test_blocks_script_payload_after_download(self) -> None:
        with patch(
            "posthog.temporal.ai.slack_app.attachments._download_slack_file",
            return_value=b"#!/bin/sh\necho unsafe\n",
        ):
            prepared = prepare_slack_file_artifacts([_slack_file(name="notes.txt")], "xoxb-token")

        assert prepared.artifacts == []
        assert prepared.skipped_messages == [
            "notes.txt was skipped because its content looks like an executable or script."
        ]

    def test_rejects_html_interstitial_response(self) -> None:
        # Slack serves an HTTP 200 HTML login page when the token can't read the
        # file; the body must not be forwarded as the attachment's content.
        response = MagicMock()
        response.is_redirect = False
        response.status_code = 200
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        with patch("posthog.temporal.ai.slack_app.attachments.slack_request", return_value=response):
            prepared = prepare_slack_file_artifacts([_slack_file()], "xoxb-token")

        assert prepared.artifacts == []
        assert prepared.skipped_messages == ["debug.log was skipped because it could not be downloaded from Slack."]

    def test_rejects_non_slack_download_url(self) -> None:
        with patch("posthog.temporal.ai.slack_app.attachments._download_slack_file") as download:
            prepared = prepare_slack_file_artifacts(
                [_slack_file(url_private_download="https://example.com/debug.log")],
                "xoxb-token",
            )

        download.assert_not_called()
        assert prepared.artifacts == []
        assert prepared.skipped_messages == ["debug.log was skipped because its download URL was not a Slack file URL."]

    def test_collects_thread_files_without_refetching_the_triggering_message(self) -> None:
        triggering_file = _slack_file(id="F_TRIGGER", name="pasted.png")
        thread_messages: list[dict[str, Any]] = [
            {"ts": "1.000", "files": [_slack_file(id="F_PARENT", name="chart.png")]},
            {"ts": "2.000"},
            # The same upload re-shared later in the thread, and the file the mention
            # itself carries — both already accounted for, neither fetched twice.
            {"ts": "3.000", "files": [_slack_file(id="F_PARENT", name="chart.png"), triggering_file]},
        ]

        with patch("posthog.temporal.ai.slack_app.attachments._download_slack_file", return_value=b"bytes") as download:
            prepared = prepare_slack_thread_file_artifacts(
                thread_messages, "xoxb-token", already_requested=[triggering_file]
            )

        assert download.call_count == 1
        assert [artifact["name"] for artifact in prepared.artifacts] == ["chart.png"]

    def test_caps_how_many_thread_files_one_turn_carries(self) -> None:
        over_cap = MAX_SLACK_ATTACHMENTS_PER_THREAD + 1
        thread_messages: list[dict[str, Any]] = [
            {"ts": f"{index}.000", "files": [_slack_file(id=f"F{index}", name=f"shot-{index}.png")]}
            for index in range(over_cap)
        ]

        with patch("posthog.temporal.ai.slack_app.attachments._download_slack_file", return_value=b"bytes"):
            prepared = prepare_slack_thread_file_artifacts(thread_messages, "xoxb-token")

        assert prepared.requested_count == over_cap
        assert len(prepared.artifacts) == MAX_SLACK_ATTACHMENTS_PER_THREAD
        assert prepared.artifacts[0]["name"] == "shot-0.png"
        assert prepared.skipped_messages == [
            f"Slack attachment(s) from earlier in the thread skipped: only {MAX_SLACK_ATTACHMENTS_PER_THREAD} "
            "thread files are supported."
        ]

    def test_build_prompt_handles_file_only_message(self) -> None:
        prompt = build_slack_attachment_prompt_text(
            None,
            uploaded_artifacts=[{"name": "debug.log"}],
            skipped_messages=[f"deploy.sh {_TYPE_SKIP_SUFFIX}"],
        )

        assert prompt == (
            "Slack attachment(s) available to the agent as task files: debug.log.\n\n"
            "Slack attachment(s) skipped:\n"
            f"- deploy.sh {_TYPE_SKIP_SUFFIX}"
        )
