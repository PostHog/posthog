from unittest.mock import Mock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

import requests
from celery.exceptions import Retry
from parameterized import parameterized

from posthog.tasks.transactional_email import send_transactional_email_task
from posthog.transactional_email import (
    TransactionalEmailDeliveryUncertain,
    TransactionalEmailRejected,
    TransactionalEmailRetryableError,
    send_transactional_email,
)

TEMPLATE_ID = "12345678-1234-5678-9abc-123456789abc"


@override_settings(
    POSTHOG_HOST="https://us.posthog.com/",
    POSTHOG_PROJECT_ID=2,
    POSTHOG_TRANSACTIONAL_EMAIL_API_KEY="phs_fake_transactional_key",
)
class TestTransactionalEmail(SimpleTestCase):
    def test_task_sends_to_configured_project_and_returns_queue_receipt(self) -> None:
        response = Mock(status_code=202)
        response.json.return_value = {"message_id": "example-message-id"}
        with patch("posthog.transactional_email.requests.post", return_value=response) as post:
            result = send_transactional_email_task.apply(
                args=[TEMPLATE_ID],
                kwargs={
                    "to": "recipient@example.com",
                    "distinct_id": "example-user",
                    "message_data": {"title": "Example report"},
                },
                throw=True,
            )

        assert result.result == "example-message-id"
        post.assert_called_once_with(
            f"https://us.posthog.com/api/projects/2/messaging_templates/{TEMPLATE_ID}/send/",
            headers={"Authorization": "Bearer phs_fake_transactional_key"},
            json={
                "to": "recipient@example.com",
                "identifiers": {"distinct_id": "example-user"},
                "message_data": {"title": "Example report"},
            },
            timeout=(3, 10),
            allow_redirects=False,
        )

    @override_settings(POSTHOG_HOST="https://eu.posthog.com", POSTHOG_PROJECT_ID=123)
    def test_supports_a_different_sending_region_without_identifiers(self) -> None:
        response = Mock(status_code=202)
        response.json.return_value = {"message_id": "example-message-id"}
        with patch("posthog.transactional_email.requests.post", return_value=response) as post:
            send_transactional_email(TEMPLATE_ID, to="recipient@example.com")

        assert post.call_args.args[0].startswith("https://eu.posthog.com/api/projects/123/")
        assert post.call_args.kwargs["json"] == {"to": "recipient@example.com", "message_data": {}}

    @parameterized.expand(
        [
            ("POSTHOG_TRANSACTIONAL_EMAIL_API_KEY", ""),
            ("POSTHOG_PROJECT_ID", 0),
            ("POSTHOG_HOST", ""),
            ("POSTHOG_HOST", "http://example.com"),
            ("POSTHOG_HOST", "https://example.com/path"),
            ("POSTHOG_HOST", "https://user:password@example.com"),
        ]
    )
    def test_invalid_configuration_does_not_send(self, setting: str, value: str | int) -> None:
        with (
            override_settings(**{setting: value}),
            patch("posthog.transactional_email.requests.post") as post,
            self.assertRaises(ImproperlyConfigured),
        ):
            send_transactional_email(TEMPLATE_ID, to="recipient@example.com")
        post.assert_not_called()

    def test_invalid_template_does_not_send(self) -> None:
        with patch("posthog.transactional_email.requests.post") as post, self.assertRaises(ImproperlyConfigured):
            send_transactional_email("../different-endpoint", to="recipient@example.com")
        post.assert_not_called()

    @parameterized.expand([(301,), (400,), (401,), (403,), (404,)])
    def test_confirmed_rejection(self, status_code: int) -> None:
        with (
            patch("posthog.transactional_email.requests.post", return_value=Mock(status_code=status_code)),
            self.assertRaises(TransactionalEmailRejected) as raised,
        ):
            send_transactional_email(TEMPLATE_ID, to="recipient@example.com")
        assert str(raised.exception) == f"http_{status_code}"

    @parameterized.expand([(200,), (408,), (500,), (503,)])
    def test_unconfirmed_response_is_uncertain(self, status_code: int) -> None:
        with (
            patch("posthog.transactional_email.requests.post", return_value=Mock(status_code=status_code)),
            self.assertRaises(TransactionalEmailDeliveryUncertain),
        ):
            send_transactional_email(TEMPLATE_ID, to="recipient@example.com")

    @parameterized.expand([(None,), ([],), ({},), ({"message_id": 123},), ({"message_id": ""},)])
    def test_acceptance_without_a_receipt_is_uncertain(self, payload: object) -> None:
        response = Mock(status_code=202)
        response.json.return_value = payload
        with (
            patch("posthog.transactional_email.requests.post", return_value=response),
            self.assertRaises(TransactionalEmailDeliveryUncertain),
        ):
            send_transactional_email(TEMPLATE_ID, to="recipient@example.com")

    def test_invalid_json_is_uncertain(self) -> None:
        response = Mock(status_code=202)
        response.json.side_effect = ValueError("private response")
        with (
            patch("posthog.transactional_email.requests.post", return_value=response),
            self.assertRaises(TransactionalEmailDeliveryUncertain) as raised,
        ):
            send_transactional_email(TEMPLATE_ID, to="recipient@example.com")
        assert str(raised.exception) == "invalid_response"
        assert raised.exception.__suppress_context__

    @parameterized.expand([(requests.ReadTimeout,), (requests.ConnectionError,)])
    def test_task_does_not_retry_uncertain_requests(self, error_type: type[requests.RequestException]) -> None:
        with patch("posthog.transactional_email.requests.post", side_effect=error_type("private request")) as post:
            result = send_transactional_email_task.apply(
                args=[TEMPLATE_ID], kwargs={"to": "recipient@example.com"}, throw=False
            )
        post.assert_called_once()
        assert isinstance(result.result, TransactionalEmailDeliveryUncertain)
        assert str(result.result) == "request_failed"

    @parameterized.expand([("connect_timeout",), ("rate_limited",)])
    def test_task_retries_only_confirmed_non_acceptance(self, failure: str) -> None:
        with patch("posthog.transactional_email.requests.post") as post:
            if failure == "connect_timeout":
                post.side_effect = requests.ConnectTimeout("private request")
            else:
                post.return_value = Mock(status_code=429)
            with self.assertRaises(Retry) as raised:
                send_transactional_email_task.apply(
                    args=[TEMPLATE_ID], kwargs={"to": "recipient@example.com"}, throw=True
                )
        post.assert_called_once()
        assert isinstance(raised.exception.exc, TransactionalEmailRetryableError)
        assert str(raised.exception.exc) == failure

    @parameterized.expand([("60", 60), ("3600", 3600), ("invalid", None), (None, None)])
    def test_rate_limit_retry_uses_server_delay(self, header: str | None, expected: int | None) -> None:
        response = Mock(status_code=429, headers={"Retry-After": header} if header is not None else {})
        with patch("posthog.transactional_email.requests.post", return_value=response) as post:
            with self.assertRaises(Retry) as raised:
                send_transactional_email_task.apply(
                    args=[TEMPLATE_ID], kwargs={"to": "recipient@example.com"}, throw=True
                )
        post.assert_called_once()
        assert isinstance(raised.exception.exc, TransactionalEmailRetryableError)
        assert raised.exception.exc.retry_after == expected
        if expected is not None:
            assert raised.exception.when == expected
