from unittest.mock import MagicMock, call, patch

from django.template.loader import render_to_string

from products.alerts.backend.email_notifications import send_alert_email


@patch("products.alerts.backend.email_notifications.EmailMessage")
def test_send_alert_email_delivers_to_every_recipient(MockEmailMessage: MagicMock) -> None:
    send_alert_email(
        recipients=("first@example.com", "second@example.com"),
        campaign_key="alert-email-test",
        subject="Alert firing",
        template_name="alert_check_firing",
        template_context={
            "match_descriptions": ["Threshold breached"],
            "insight_url": "/project/1/insights/example",
            "insight_name": "Example insight",
            "alert_url": "/project/1/insights/example?alert_id=1",
            "alert_name": "Example alert",
            "project_name": "Example project",
        },
    )

    MockEmailMessage.assert_called_once_with(
        campaign_key="alert-email-test",
        subject="Alert firing",
        template_name="alert_check_firing",
        template_context={
            "match_descriptions": ["Threshold breached"],
            "insight_url": "/project/1/insights/example",
            "insight_name": "Example insight",
            "alert_url": "/project/1/insights/example?alert_id=1",
            "alert_name": "Example alert",
            "project_name": "Example project",
        },
    )
    message = MockEmailMessage.return_value
    assert message.add_recipient.call_args_list == [
        call(email="first@example.com"),
        call(email="second@example.com"),
    ]
    message.send.assert_called_once_with()


def test_alert_firing_email_labels_test_delivery_without_claiming_the_alert_is_firing() -> None:
    html = render_to_string(
        "email/alert_check_firing.html",
        {
            "match_descriptions": ["This is a test alert. No action is needed."],
            "insight_url": "/project/1/insights/example",
            "insight_name": "Example insight",
            "alert_url": "/project/1/insights/example?alert_id=1",
            "alert_name": "Example alert",
            "project_name": "Example project",
            "is_test": True,
        },
    )

    assert "This is a test delivery" in html
    assert "alert is firing" not in html
