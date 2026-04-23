import pytest
from unittest.mock import MagicMock, patch

import requests

from products.conversations.backend.mailgun import (
    MailgunDomainConflict,
    MailgunDomainNotRegistered,
    MailgunNotConfigured,
    MailgunPermanentError,
    MailgunTransientError,
    add_domain,
    send_mime,
)


def _mailgun_response(status_code: int, body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {}
    resp.raise_for_status = MagicMock()
    return resp


@patch("products.conversations.backend.mailgun.get_instance_setting", return_value="fake-api-key")
@patch("products.conversations.backend.mailgun.requests.post")
class TestAddDomain:
    def test_already_exists_raises_instead_of_adopting(self, mock_post: MagicMock, _mock_key: MagicMock):
        mock_post.return_value = _mailgun_response(400, {"message": "domain example.com already exists"})

        with pytest.raises(MailgunDomainConflict, match="already exists"):
            add_domain("example.com")

    def test_already_taken_still_raises(self, mock_post: MagicMock, _mock_key: MagicMock):
        mock_post.return_value = _mailgun_response(
            400, {"message": "domain example.com is already taken by another account"}
        )

        with pytest.raises(MailgunDomainConflict, match="another Mailgun account"):
            add_domain("example.com")

    def test_success_returns_sending_dns_records(self, mock_post: MagicMock, _mock_key: MagicMock):
        mock_post.return_value = _mailgun_response(
            201,
            {
                "sending_dns_records": [
                    {"record_type": "TXT", "name": "example.com", "value": "v=spf1"},
                    {"record_type": "CNAME", "name": "track.example.com", "value": "m.mg"},
                ]
            },
        )

        result = add_domain("example.com")

        assert [r["record_type"] for r in result["sending_dns_records"]] == ["TXT"]

    def test_case_insensitive_already_exists_match(self, mock_post: MagicMock, _mock_key: MagicMock):
        mock_post.return_value = _mailgun_response(400, {"message": "Domain Already EXISTS"})

        with pytest.raises(MailgunDomainConflict, match="already exists"):
            add_domain("example.com")

    def test_unrecognised_400_falls_through_to_raise_for_status(self, mock_post: MagicMock, _mock_key: MagicMock):
        resp = _mailgun_response(400, {"message": "some other error"})
        resp.raise_for_status.side_effect = RuntimeError("http 400")
        mock_post.return_value = resp

        with pytest.raises(RuntimeError, match="http 400"):
            add_domain("example.com")


@patch("products.conversations.backend.mailgun.get_instance_setting", return_value="")
class TestGetApiKey:
    def test_raises_mailgun_not_configured_when_key_missing(self, _mock_setting: MagicMock):
        from products.conversations.backend.mailgun import _get_api_key

        with pytest.raises(MailgunNotConfigured):
            _get_api_key()


def _send_response(status_code: int, body: dict | None = None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {}
    resp.text = text or (str(body) if body else "")
    return resp


@patch("products.conversations.backend.mailgun.get_instance_setting", return_value="fake-api-key")
@patch("products.conversations.backend.mailgun.requests.post")
class TestSendMime:
    MIME = b"From: support@example.com\r\nTo: user@example.com\r\n\r\nhello"
    RECIPIENTS = ["user@example.com", "cc1@example.com", "cc2@example.com"]

    def test_success_forwards_all_fields_and_tracking_flags(self, mock_post: MagicMock, _mock_key: MagicMock):
        mock_post.return_value = _send_response(200, {"id": "<mailgun-id@example.com>"})

        result = send_mime("example.com", self.MIME, recipients=self.RECIPIENTS)

        assert result == "<mailgun-id@example.com>"
        assert mock_post.call_count == 1
        _, kwargs = mock_post.call_args

        assert kwargs["auth"] == ("api", "fake-api-key")

        # All recipients as repeated `to` form keys
        to_entries = [value for key, value in kwargs["data"] if key == "to"]
        assert to_entries == self.RECIPIENTS

        # Tracking flags explicitly disabled regardless of account defaults
        form_pairs = list(kwargs["data"])
        assert ("o:tracking", "no") in form_pairs
        assert ("o:tracking-clicks", "no") in form_pairs
        assert ("o:tracking-opens", "no") in form_pairs

        # MIME uploaded as a file part
        message_part = kwargs["files"]["message"]
        assert message_part[0] == "message.mime"
        assert message_part[1] == self.MIME

        # URL hits the per-domain endpoint
        assert "/example.com/messages.mime" in mock_post.call_args[0][0]

    def test_crlf_preserved_in_uploaded_bytes(self, mock_post: MagicMock, _mock_key: MagicMock):
        """Regression guard for the explicit linesep='\\r\\n' at call sites."""
        mock_post.return_value = _send_response(200, {"id": "x"})

        send_mime("example.com", self.MIME, recipients=self.RECIPIENTS)

        uploaded = mock_post.call_args.kwargs["files"]["message"][1]
        assert b"\r\n" in uploaded

    def test_404_raises_domain_not_registered(self, mock_post: MagicMock, _mock_key: MagicMock):
        mock_post.return_value = _send_response(404, text="domain not found")

        with pytest.raises(MailgunDomainNotRegistered):
            send_mime("example.com", self.MIME, recipients=self.RECIPIENTS)

    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    def test_transient_status_raises_transient(self, mock_post: MagicMock, _mock_key: MagicMock, status: int):
        mock_post.return_value = _send_response(status, text="try again later")

        with pytest.raises(MailgunTransientError):
            send_mime("example.com", self.MIME, recipients=self.RECIPIENTS)

    @pytest.mark.parametrize("status", [400, 401, 403, 413])
    def test_other_4xx_raises_permanent(self, mock_post: MagicMock, _mock_key: MagicMock, status: int):
        mock_post.return_value = _send_response(status, text="nope")

        with pytest.raises(MailgunPermanentError):
            send_mime("example.com", self.MIME, recipients=self.RECIPIENTS)

    def test_connection_error_is_transient(self, mock_post: MagicMock, _mock_key: MagicMock):
        mock_post.side_effect = requests.exceptions.ConnectionError("conn reset")

        with pytest.raises(MailgunTransientError):
            send_mime("example.com", self.MIME, recipients=self.RECIPIENTS)

    def test_timeout_is_transient(self, mock_post: MagicMock, _mock_key: MagicMock):
        mock_post.side_effect = requests.exceptions.Timeout("slow")

        with pytest.raises(MailgunTransientError):
            send_mime("example.com", self.MIME, recipients=self.RECIPIENTS)
