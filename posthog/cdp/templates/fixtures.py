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
