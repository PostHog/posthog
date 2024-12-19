from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

template_error_tracking_alert: HogFunctionTemplate = HogFunctionTemplate(
    status="free",
    type="error_tracking_alert",
    id="template-error-tracking-alert",
    name="Error Tracking Issue Alert",
    description="",
    icon_url="/static/services/slack.png",
    category=["Error Tracking"],
    filters={"trigger": "created"},
    hog="""
let res := fetch('https://slack.com/api/chat.postMessage', {
  'body': {
    'channel': inputs.channel,
    'icon_emoji': inputs.icon_emoji,
    'username': inputs.username,
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
            "required": True,
        },
        {
            "key": "channel",
            "type": "integration_field",
            "integration_key": "slack_workspace",
            "integration_field": "slack_channel",
            "label": "Channel to post to",
            "description": "Select the channel to post to (e.g. #general). The PostHog app must be installed in the workspace.",
            "secret": False,
            "required": True,
        },
        {
            "key": "icon_emoji",
            "type": "string",
            "label": "Emoji icon",
            "default": ":hedgehog:",
            "required": False,
            "secret": False,
        },
        {
            "key": "username",
            "type": "string",
            "label": "Bot name",
            "default": "PostHog",
            "required": False,
            "secret": False,
        },
    ],
)
