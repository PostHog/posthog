from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
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
            "hidden": False,
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
            "hidden": False,
            "required": True,
        },
        {
            "key": "icon_emoji",
            "type": "string",
            "label": "Emoji icon",
            "default": ":hedgehog:",
            "required": False,
            "secret": False,
            "hidden": False,
        },
        {
            "key": "username",
            "type": "string",
            "label": "Bot name",
            "default": "PostHog",
            "required": False,
            "secret": False,
            "hidden": False,
        },
        {
            "key": "blocks",
            "type": "json",
            "label": "Blocks",
            "description": "(see https://api.slack.com/block-kit/building)",
            "default": [
                {
                    "text": {
                        "text": "*{person.name}* triggered event: '{event.event}'",
                        "type": "mrkdwn",
                    },
                    "type": "section",
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "url": "{person.url}",
                            "text": {"text": "View Person in PostHog", "type": "plain_text"},
                            "type": "button",
                        },
                        {
                            "url": "{source.url}",
                            "text": {"text": "Message source", "type": "plain_text"},
                            "type": "button",
                        },
                    ],
                },
            ],
            "secret": False,
            "required": False,
            "hidden": False,
        },
        {
            "key": "text",
            "type": "string",
            "label": "Plain text message",
            "description": "Optional fallback message if blocks are not provided or supported",
            "default": "*{person.name}* triggered event: '{event.event}'",
            "secret": False,
            "required": False,
            "hidden": False,
        },
    ],
)
