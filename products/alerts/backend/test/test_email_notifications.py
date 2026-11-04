from unittest.mock import MagicMock, call, patch

from django.template.loader import render_to_string

from posthog.tasks.alerts.utils import InvestigationSummaryLine, send_notifications_for_breaches

from products.alerts.backend.facade.email import send_alert_email
from products.alerts.backend.models import AlertConfiguration


def test_investigation_summary_renders_markdown_in_email_and_plain_text_in_destinations() -> None:
    alert = MagicMock(spec=AlertConfiguration)
    alert.get_subscribed_users_emails.return_value = ["reader@example.com"]
    markdown = "- `signup_count` reached **40**"
    breaches = ["Anomaly in <script>series</script>.", "signup_count reached 40.", "See the notebook."]

    with (
        patch("posthog.tasks.alerts.utils.send_alert_email") as email,
        patch("posthog.tasks.alerts.utils.trigger_alert_hog_functions", return_value=[]) as destinations,
    ):
        send_notifications_for_breaches(
            alert,
            breaches,
            "example-check",
            investigation_summary=InvestigationSummaryLine(index=1, markdown=markdown),
        )

    html = render_to_string("email/alert_check_firing.html", email.call_args.kwargs["template_context"])
    assert "<strong>40</strong>" in html
    assert "<p>Anomaly in &lt;script&gt;series&lt;/script&gt;.</p>" in html
    assert destinations.call_args.kwargs["properties"]["breaches"] == "\n".join(breaches)


@patch("products.alerts.backend.facade.email.is_email_available", return_value=True)
@patch("products.alerts.backend.facade.email.EmailMessage")
def test_send_alert_email_delivers_to_every_recipient(MockEmailMessage: MagicMock, _mock_available: MagicMock) -> None:
    assert send_alert_email(
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


def test_alert_firing_email_lists_every_breach_description() -> None:
    html = render_to_string(
        "email/alert_check_firing.html",
        {
            "match_descriptions": ["Signups dropped below 100", "Signups dropped below 50"],
            "insight_url": "/project/1/insights/example",
            "insight_name": "Example insight",
            "alert_url": "/project/1/insights/example?alert_id=1",
            "alert_name": "Example alert",
            "project_name": "Example project",
        },
    )

    assert "Signups dropped below 100" in html
    assert "Signups dropped below 50" in html


def test_alert_evaluation_failure_email_claims_no_cause_for_an_unavailable_detector() -> None:
    html = render_to_string(
        "email/alert_check_failed_to_evaluate.html",
        {
            "alert_error": "The AI detector could not complete this check.",
            "alert_url": "/project/1/insights/example?alert_id=1",
            "alert_name": "Example alert",
            "insight_url": "/project/1/insights/example",
            "insight_name": "Example insight",
            "detector_unavailable": True,
        },
    )

    assert "could not run the AI detector" in html
    assert "model provider" not in html
    assert "there is nothing to change" not in html
    assert "Review the alert settings" not in html
    assert "settings need attention" not in html
    assert "PostHog will try again" in html
    assert "View alert" in html


def test_alert_evaluation_failure_email_includes_the_reason_and_next_check_timing() -> None:
    html = render_to_string(
        "email/alert_check_failed_to_evaluate.html",
        {
            "alert_error": "The query could not run.",
            "alert_url": "/project/1/insights/example?alert_id=1",
            "alert_name": "Example alert",
            "insight_url": "/project/1/insights/example",
            "insight_name": "Example insight",
        },
    )

    assert "The query could not run." in html
    assert "PostHog could not evaluate this alert." in html
    assert "PostHog has a temporary problem" in html
    assert "Insight" in html
    assert "Error" in html
    assert "Review the alert settings" in html
    assert "PostHog will try again" in html
    assert "next scheduled check" in html
    assert "contact" in html
    assert "support" in html
    assert "Review alert" in html
    assert "alert_id=1" in html
    assert "Example insight" in html
