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

# The PagerDuty destination lives in nodejs (nodejs/src/cdp/templates/_destinations/pagerduty). Tests
# that create alert destinations sync this stand-in. Keep its input keys and secret flags the same as
# the nodejs template, because the alert destination builder writes those keys and the
# HogFunctionSerializer moves the secret ones to encrypted inputs.
template_pagerduty = HogFunctionTemplateDC(
    status="beta",
    free=True,
    type="destination",
    id="template-pagerduty",
    name="PagerDuty",
    description="Triggers, acknowledges or resolves a PagerDuty incident",
    icon_url="/static/services/pagerduty.png",
    category=["Monitoring & Alerts"],
    code_language="hog",
    code="""
let res := fetch('https://events.pagerduty.com/v2/enqueue', {
  'body': {
    'routing_key': inputs.routing_key,
    'event_action': inputs.event_action,
    'dedup_key': inputs.dedup_key
  },
  'method': 'POST',
  'headers': {
    'Content-Type': 'application/json'
  }
});

if (res.status >= 400) {
  throw Error(f'PagerDuty rejected the event: {res.status}: {res.body}');
}
""".strip(),
    inputs_schema=[
        {"key": "routing_key", "type": "string", "label": "Routing key", "secret": True, "required": True},
        {"key": "event_action", "type": "choice", "label": "Event action", "secret": False, "required": True},
        {"key": "dedup_key", "type": "string", "label": "Dedup key", "secret": False, "required": False},
        {"key": "summary", "type": "string", "label": "Summary", "secret": False, "required": True},
        {"key": "source", "type": "string", "label": "Source", "secret": False, "required": True},
        {"key": "severity", "type": "choice", "label": "Severity", "secret": False, "required": True},
        {"key": "component", "type": "string", "label": "Component", "secret": False, "required": False},
        {"key": "event_class", "type": "string", "label": "Class", "secret": False, "required": False},
        {"key": "custom_details", "type": "json", "label": "Custom details", "secret": False, "required": False},
        {"key": "links", "type": "json", "label": "Links", "secret": False, "required": False},
    ],
)
