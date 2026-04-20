import json
import base64
from unittest.mock import patch

from posthog.temporal.ai.posthog_code_slack_attachments import (
    CLOUD_PROMPT_PREFIX,
    encode_user_message_with_attachments,
)


def _file(file_id="F1", name="errors.log", mimetype="text/plain", url="https://files.slack.com/F1/errors.log"):
    return {
        "id": file_id,
        "name": name,
        "mimetype": mimetype,
        "url_private_download": url,
    }


class TestEncodeUserMessageWithAttachments:
    def test_returns_plain_text_when_no_files(self):
        assert encode_user_message_with_attachments("hello", None, "xoxb-token") == "hello"
        assert encode_user_message_with_attachments("hello", [], "xoxb-token") == "hello"

    def test_returns_plain_text_when_no_bot_token(self):
        assert encode_user_message_with_attachments("hello", [_file()], None) == "hello"
        assert encode_user_message_with_attachments("hello", [_file()], "") == "hello"

    def test_returns_plain_text_when_all_downloads_fail(self):
        with patch(
            "posthog.temporal.ai.posthog_code_slack_attachments._download_slack_file",
            return_value=None,
        ):
            result = encode_user_message_with_attachments("hello", [_file()], "xoxb-token")
        assert result == "hello"

    def test_encodes_text_file_as_resource_block(self):
        payload = b"line 1\nline 2\n"
        with patch(
            "posthog.temporal.ai.posthog_code_slack_attachments._download_slack_file",
            return_value=payload,
        ):
            result = encode_user_message_with_attachments(
                "check this log",
                [_file(file_id="F123", name="errors.log", mimetype="text/plain")],
                "xoxb-token",
            )

        assert result.startswith(CLOUD_PROMPT_PREFIX)
        body = json.loads(result[len(CLOUD_PROMPT_PREFIX) :])
        assert body["blocks"][0] == {"type": "text", "text": "check this log"}
        assert body["blocks"][1] == {
            "type": "resource",
            "resource": {
                "uri": "attachment://F123?label=errors.log",
                "text": "line 1\nline 2\n",
                "mimeType": "text/plain",
            },
        }

    def test_encodes_image_as_image_block(self):
        image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        with patch(
            "posthog.temporal.ai.posthog_code_slack_attachments._download_slack_file",
            return_value=image_bytes,
        ):
            result = encode_user_message_with_attachments(
                "look",
                [_file(file_id="F9", name="screenshot.png", mimetype="image/png")],
                "xoxb-token",
            )

        assert result.startswith(CLOUD_PROMPT_PREFIX)
        body = json.loads(result[len(CLOUD_PROMPT_PREFIX) :])
        assert body["blocks"][1] == {
            "type": "image",
            "uri": "attachment://F9?label=screenshot.png",
            "data": base64.b64encode(image_bytes).decode("ascii"),
            "mimeType": "image/png",
        }

    def test_encodes_binary_as_resource_blob(self):
        pdf_bytes = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
        with patch(
            "posthog.temporal.ai.posthog_code_slack_attachments._download_slack_file",
            return_value=pdf_bytes,
        ):
            result = encode_user_message_with_attachments(
                "see pdf",
                [_file(file_id="Fpdf", name="report final.pdf", mimetype="application/pdf")],
                "xoxb-token",
            )

        assert result.startswith(CLOUD_PROMPT_PREFIX)
        body = json.loads(result[len(CLOUD_PROMPT_PREFIX) :])
        # Filename gets URL-encoded (space -> %20)
        assert body["blocks"][1]["resource"]["uri"] == "attachment://Fpdf?label=report%20final.pdf"
        assert body["blocks"][1]["resource"]["blob"] == base64.b64encode(pdf_bytes).decode("ascii")
        assert body["blocks"][1]["resource"]["mimeType"] == "application/pdf"
        assert "text" not in body["blocks"][1]["resource"]

    def test_text_file_with_non_utf8_bytes_falls_back_to_blob(self):
        non_utf8 = b"\xff\xfe\x00notvalidutf8"
        with patch(
            "posthog.temporal.ai.posthog_code_slack_attachments._download_slack_file",
            return_value=non_utf8,
        ):
            result = encode_user_message_with_attachments(
                "check",
                [_file(mimetype="text/x-custom")],
                "xoxb-token",
            )

        body = json.loads(result[len(CLOUD_PROMPT_PREFIX) :])
        assert "blob" in body["blocks"][1]["resource"]

    def test_skips_non_dict_files(self):
        payload = b"hello"
        with patch(
            "posthog.temporal.ai.posthog_code_slack_attachments._download_slack_file",
            return_value=payload,
        ):
            result = encode_user_message_with_attachments(
                "msg",
                ["not-a-dict", _file()],  # type: ignore[list-item]
                "xoxb-token",
            )

        body = json.loads(result[len(CLOUD_PROMPT_PREFIX) :])
        # One text + one file block (the non-dict entry was skipped)
        assert len(body["blocks"]) == 2

    def test_skips_file_with_no_source_url(self):
        bad = {"id": "F2", "name": "x.txt", "mimetype": "text/plain"}
        result = encode_user_message_with_attachments("msg", [bad], "xoxb-token")
        assert result == "msg"

    def test_omits_text_block_when_message_is_empty(self):
        with patch(
            "posthog.temporal.ai.posthog_code_slack_attachments._download_slack_file",
            return_value=b"data",
        ):
            result = encode_user_message_with_attachments("", [_file()], "xoxb-token")

        body = json.loads(result[len(CLOUD_PROMPT_PREFIX) :])
        assert len(body["blocks"]) == 1
        assert body["blocks"][0]["type"] == "resource"

    def test_mixed_success_and_failure_includes_only_successful(self):
        calls = {"n": 0}

        def fake_download(url, token):
            calls["n"] += 1
            return b"data" if calls["n"] == 1 else None

        with patch(
            "posthog.temporal.ai.posthog_code_slack_attachments._download_slack_file",
            side_effect=fake_download,
        ):
            result = encode_user_message_with_attachments(
                "hi",
                [_file(file_id="F1"), _file(file_id="F2")],
                "xoxb-token",
            )

        body = json.loads(result[len(CLOUD_PROMPT_PREFIX) :])
        assert len(body["blocks"]) == 2  # text + first file only
        assert body["blocks"][1]["resource"]["uri"].startswith("attachment://F1")

    def test_allowed_host_check_rejects_non_slack_hosts(self):
        from posthog.temporal.ai.posthog_code_slack_attachments import _is_allowed_slack_file_url

        assert _is_allowed_slack_file_url("https://files.slack.com/abc")
        assert _is_allowed_slack_file_url("https://foo.slack-edge.com/bar")
        assert _is_allowed_slack_file_url("https://slack-files.com/x")
        assert not _is_allowed_slack_file_url("http://files.slack.com/abc")  # http not https
        assert not _is_allowed_slack_file_url("https://evil.example.com/files.slack.com")
        assert not _is_allowed_slack_file_url("https://example.com/")
