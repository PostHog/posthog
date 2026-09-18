from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

# The Slack destination itself lives in nodejs (nodejs/src/cdp/templates/_destinations/slack). Tests
# that need a real destination template in the database sync this stand-in instead of reaching out to
# the plugin server. It does not have to track the nodejs template field for field.
template_slack = HogFunctionTemplateDC(
    status="stable",
    free=True,
    type="destination",
    id="template-slack",
    name="Slack",
    description="Sends a message to a Slack channel",
    icon_url="/static/services/slack.png",
    category=["Customer Success"],
    code_language="hog",
    code="""
let res := fetch('https://slack.com/api/chat.postMessage', {
  'body': {
    'channel': inputs.channel,
    'blocks': inputs.blocks,
    'text': inputs.text
  },
  'method': 'POST',
  'headers': {
    'Authorization': f'Bearer {inputs.slack_workspace.access_token}',
    'Content-Type': 'application/json'
  }
});

if (res.status != 200 or res.body.ok == false) {
  throw Error(f'Failed to post message to Slack: {res.status}: {res.body}');
}
""".strip(),
    inputs_schema=[
        {
            "key": "slack_workspace",
            "type": "integration",
            "integration": "slack",
            "label": "Slack workspace",
            "requiredScopes": "channels:read groups:read chat:write chat:write.customize",
            "secret": False,
            "hidden": False,
            "required": True,
        },
        {
            "key": "channel",
            "type": "integration_field",
            "integration_key": "slack_workspace",
            "integration_field": "slack_channel",
            "label": "Channel to post to",
            "secret": False,
            "hidden": False,
            "required": True,
        },
        {
            "key": "blocks",
            "type": "json",
            "label": "Blocks",
            "secret": False,
            "required": False,
            "hidden": False,
        },
        {
            "key": "text",
            "type": "string",
            "label": "Plain text message",
            "secret": False,
            "required": False,
            "hidden": False,
        },
        {
            "key": "thread_ts",
            "type": "string",
            "label": "Reply in thread",
            "secret": False,
            "required": False,
            "hidden": False,
        },
    ],
)

# Same arrangement for the PagerDuty destination (nodejs/src/cdp/templates/_destinations/pagerduty).
# The inputs schema does track the nodejs template, because which inputs are secret decides what a
# saved destination keeps in `inputs` versus `encrypted_inputs`, and the alert destination tests
# depend on that split.
template_pagerduty = HogFunctionTemplateDC(
    status="stable",
    free=True,
    type="destination",
    id="template-pagerduty",
    name="PagerDuty",
    description="Sends an event to the PagerDuty Events API v2 to trigger, acknowledge or resolve an incident",
    icon_url="/static/services/pagerduty.png",
    category=["Monitoring & Alerts"],
    code_language="hog",
    code="""
let endpoint := 'https://events.pagerduty.com/v2/enqueue'
if (inputs.region == 'eu') {
    endpoint := 'https://events.eu.pagerduty.com/v2/enqueue'
}

let payload := {
    'summary': inputs.summary,
    'source': inputs.source,
    'severity': inputs.severity
}
if (not empty(inputs.custom_details)) {
    payload['custom_details'] := inputs.custom_details
}

let body := {
    'routing_key': inputs.routing_key,
    'event_action': inputs.event_action,
    'payload': payload,
    'client': 'PostHog'
}
if (not empty(inputs.dedup_key)) {
    body['dedup_key'] := inputs.dedup_key
}
if (not empty(inputs.links)) {
    body['links'] := inputs.links
}
if (not empty(inputs.client_url)) {
    body['client_url'] := inputs.client_url
}

let res := fetch(endpoint, {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json'
    },
    'body': body
});

if (res.status >= 400) {
    throw Error(f'Failed to send event to PagerDuty: {res.status}: {res.body}');
}
""".strip(),
    inputs_schema=[
        {"key": "routing_key", "type": "string", "label": "Integration key", "secret": True, "required": True},
        {
            "key": "region",
            "type": "choice",
            "label": "Service region",
            "choices": [{"label": "US", "value": "us"}, {"label": "EU", "value": "eu"}],
            "default": "us",
            "secret": False,
            "required": True,
        },
        {
            "key": "event_action",
            "type": "choice",
            "label": "Event action",
            "choices": [
                {"label": "Trigger", "value": "trigger"},
                {"label": "Acknowledge", "value": "acknowledge"},
                {"label": "Resolve", "value": "resolve"},
            ],
            "default": "trigger",
            "secret": False,
            "required": True,
        },
        {"key": "dedup_key", "type": "string", "label": "Deduplication key", "secret": False, "required": False},
        {"key": "summary", "type": "string", "label": "Summary", "secret": False, "required": True},
        {"key": "source", "type": "string", "label": "Source", "secret": False, "required": True},
        {
            "key": "severity",
            "type": "choice",
            "label": "Severity",
            "choices": [
                {"label": "Critical", "value": "critical"},
                {"label": "Error", "value": "error"},
                {"label": "Warning", "value": "warning"},
                {"label": "Info", "value": "info"},
            ],
            "default": "critical",
            "secret": False,
            "required": True,
        },
        {"key": "custom_details", "type": "json", "label": "Custom details", "secret": False, "required": False},
        {"key": "links", "type": "json", "label": "Links", "secret": False, "required": False},
        {"key": "client_url", "type": "string", "label": "Client URL", "secret": False, "required": False},
    ],
)
