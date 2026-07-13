from common.alerting.destinations import Button, EventKindSpec, build_email_destination_config, slack_blocks, teams_text

DEFAULT_SPEC = EventKindSpec(
    event_id="$insight_alert_firing",
    display_kind="firing",
    header="Insight alert firing",
    details=(("Threshold", "30"),),
    button_url="https://example.com/insight",
    button_label="View insight",
    webhook_body={},
)

PROSE_SPEC = EventKindSpec(
    event_id="$insight_alert_firing",
    display_kind="firing",
    header="Insight alert firing",
    details=(),
    button_url="https://example.com/insight",
    button_label="View insight",
    webhook_body={},
    body_lines=("Pageviews is 42, breaching 30", "Signups is 7, breaching 5"),
    extra_buttons=(Button(url="https://example.com/alert", label="Manage alert"),),
)


class TestSpecVocabularyRendering:
    def test_slack_renders_prose_lines_and_extra_buttons(self) -> None:
        blocks = slack_blocks(PROSE_SPEC, context_elements=())

        section = next(b for b in blocks if b["type"] == "section")
        assert "Pageviews is 42, breaching 30\nSignups is 7, breaching 5" in section["text"]["text"]

        actions = next(b for b in blocks if b["type"] == "actions")
        assert [(e["url"], e["text"]["text"]) for e in actions["elements"]] == [
            ("https://example.com/insight", "View insight"),
            ("https://example.com/alert", "Manage alert"),
        ]

    def test_teams_renders_prose_lines_and_extra_buttons(self) -> None:
        text = teams_text(PROSE_SPEC)
        assert "Pageviews is 42, breaching 30" in text
        assert "[View insight](https://example.com/insight) · [Manage alert](https://example.com/alert)" in text

    def test_defaults_render_single_button_and_details_only(self) -> None:
        blocks = slack_blocks(DEFAULT_SPEC, context_elements=())
        actions = next(b for b in blocks if b["type"] == "actions")
        assert len(actions["elements"]) == 1
        assert teams_text(DEFAULT_SPEC) == (
            "**Insight alert firing**\n\n**Threshold:** 30\n\n[View insight](https://example.com/insight)"
        )

    def test_email_destination_renders_vocabulary_into_native_email_input(self) -> None:
        config = build_email_destination_config(
            team=object(),
            spec=PROSE_SPEC,
            alert_id="alert-1",
            alert_name="My alert",
            name="Email · firing · My alert",
            to_email="oncall@example.com",
        )

        assert config.payload["template_id"] == "template-email"
        assert config.payload["filters"]["properties"][0] == {
            "key": "alert_id",
            "value": "alert-1",
            "operator": "exact",
            "type": "event",
        }

        email = config.payload["inputs"]["email"]["value"]
        assert email["to"] == {"email": "oncall@example.com", "name": ""}
        assert email["subject"] == "Insight alert firing"
        assert "<p>Pageviews is 42, breaching 30</p>" in email["html"]
        assert '<a href="https://example.com/alert">Manage alert</a>' in email["html"]
        assert "Manage alert: https://example.com/alert" in email["text"]
        # Stored without a templating key: the CDP runtime then defaults to hog
        # templating, matching the placeholder syntax shared with slack/teams.
        assert "templating" not in config.payload["inputs"]["email"]
