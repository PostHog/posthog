# Recipe — deliver an insight alert to Slack or a webhook

## Payload

Use `type=internal_destination`, `template_id=template-slack` (or `template-webhook`), and:

    filters = {
      "events": [{"id": "$insight_alert_firing", "type": "events"}],
      "properties": [{"key": "alert_id", "value": "<alert_id>", "operator": "exact", "type": "event"}]
    }

    # Slack. Channel id is preferred (e.g. C0123ABC); "#general" is also accepted.
    # Override text + blocks with the same shape the alert-wizard UI uses, so agent-created and
    # UI-created alerts produce identical Slack messages.
    # Source of truth: HOG_FUNCTION_SUB_TEMPLATES['insight-alert-firing'] for template-slack
    # in frontend/src/scenes/hog-functions/sub-templates/sub-templates.ts.
    inputs = {
      "slack_workspace": {"value": <slack_integration_id_int>},
      "channel": {"value": "<channel_id>"},
      "text": {"value": "Alert triggered: {event.properties.insight_name}"},
      "blocks": {"value": [
        {"type": "header", "text": {"type": "plain_text",
          "text": "Alert '{event.properties.alert_name}' firing for insight '{event.properties.insight_name}'"}},
        {"type": "section", "text": {"type": "plain_text", "text": "{event.properties.breaches}"}},
        {"type": "context", "elements": [{"type": "mrkdwn",
          "text": "Project: <{project.url}|{project.name}>"}]},
        {"type": "divider"},
        {"type": "actions", "elements": [
          {"type": "button", "text": {"type": "plain_text", "text": "View Insight"},
           "url": "{project.url}/insights/{event.properties.insight_id}"},
          {"type": "button", "text": {"type": "plain_text", "text": "View Alert"},
           "url": "{project.url}/insights/{event.properties.insight_id}/alerts?alert_id={event.properties.alert_id}"}
        ]}
      ]}
    }

    # Webhook — must be an https:// URL.
    inputs = {"url": {"value": "<destination_url>"}}

## $insight_alert_firing event properties available for templating

`alert_id`, `alert_name`, `insight_name`, `insight_id` (short_id), `state` (always "Firing" — the
event is only emitted on a firing transition, not on recovery), `last_checked_at` (ISO 8601 string
or null), `breaches` (human-readable summary, e.g. "Series A is below 1000"), and detector
metadata: `alert_mode` (always present), `detector_type` and `ensemble_operator` (null for
threshold alerts, set for anomaly detection). Project context is available as `{project.url}`
(already includes /project/<team_id>), `{project.id}`, `{project.name}`. Do not reference `value`,
`threshold_lower`, or `insight_url` — those are not emitted.
