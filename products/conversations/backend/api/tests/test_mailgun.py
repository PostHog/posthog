import pytest
from unittest.mock import MagicMock, patch

from products.conversations.backend.mailgun import add_domain


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

        with pytest.raises(ValueError, match="already exists"):
            add_domain("example.com")

    def test_already_taken_still_raises(self, mock_post: MagicMock, _mock_key: MagicMock):
        mock_post.return_value = _mailgun_response(
            400, {"message": "domain example.com is already taken by another account"}
        )

        with pytest.raises(ValueError, match="another Mailgun account"):
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

        with pytest.raises(ValueError, match="already exists"):
            add_domain("example.com")

    def test_unrecognised_400_falls_through_to_raise_for_status(self, mock_post: MagicMock, _mock_key: MagicMock):
        resp = _mailgun_response(400, {"message": "some other error"})
        resp.raise_for_status.side_effect = RuntimeError("http 400")
        mock_post.return_value = resp

        with pytest.raises(RuntimeError, match="http 400"):
            add_domain("example.com")
