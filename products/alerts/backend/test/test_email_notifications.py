import pytest
from unittest.mock import MagicMock, call, patch

from django.template.loader import render_to_string

from posthog.helpers.email_formatting import render_markdown_email_html
from posthog.tasks.alerts.utils import send_notifications_for_breaches

from products.alerts.backend.facade.email import send_alert_email
from products.alerts.backend.models import AlertConfiguration


@pytest.mark.parametrize(
    "description_length,is_investigation",
    [(100, False), (100, True), (2999, True), (3000, True), (3001, True), (12000, True)],
)
def test_breach_delivery_preserves_email_text_and_bounds_destination_text(
    description_length: int, is_investigation: bool
) -> None:
    alert = MagicMock(spec=AlertConfiguration)
    alert.get_subscribed_users_emails.return_value = ["reader@example.com"]
    label = "Anomaly detected in [metric](https://example.com) **count** <value>."
    summary = "x" * (description_length - len(label) - 1)
    breaches = [label, summary]
    properties = {"investigation_notebook_url": "https://example.com/notebooks/example"}
    if is_investigation:
        properties["investigation_summary"] = summary

    with (
        patch("posthog.tasks.alerts.utils.send_alert_email") as email,
        patch("posthog.tasks.alerts.utils.trigger_alert_hog_functions", return_value=[]) as destinations,
    ):
        send_notifications_for_breaches(alert, breaches, "example-check", extra_properties=properties)

    context = email.call_args.kwargs["template_context"]
    assert context["match_descriptions"] == breaches
    if is_investigation:
        assert summary in context["match_descriptions_html"][1]
        assert "[metric](https://example.com) **count** &lt;value&gt;" in context["match_descriptions_html"][0]
    else:
        assert context["match_descriptions_html"] == []
    sent = destinations.call_args.kwargs["properties"]
    assert sent["investigation_notebook_url"] == properties["investigation_notebook_url"]
    assert len(sent["breaches"]) <= 3000
    assert sent["breaches"].startswith(label + "\n")
    if len("\n".join(breaches)) <= 3000:
        assert sent["breaches"] == "\n".join(breaches)
    else:
        assert sent["breaches"].endswith("…")


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
            "match_descriptions_html": [
                render_markdown_email_html("Signups dropped below 100"),
                render_markdown_email_html("Signups dropped below 50"),
                render_markdown_email_html(
                    "- `signup_count` reached **40** during _09:00–10:00_.\n"
                    "- Review [the insight](https://us.posthog.com/project/1/insights/example)."
                ),
            ],
            "insight_url": "/project/1/insights/example",
            "insight_name": "Example insight",
            "alert_url": "/project/1/insights/example?alert_id=1",
            "alert_name": "Example alert",
            "project_name": "Example project",
        },
    )

    assert "Signups dropped below 100" in html
    assert "Signups dropped below 50" in html
    assert "<code>signup_count</code>" in html
    assert "<strong>40</strong>" in html
    assert "<em>09:00–10:00</em>" in html
    assert 'href="https://us.posthog.com/project/1/insights/example"' in html


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
