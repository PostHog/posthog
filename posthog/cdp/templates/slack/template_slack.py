from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

# NOTE: Slack template is essentially just a webhook template with limited options

template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-slack",
    name="Slack webhook",
    description="Sends a webhook templated by the incoming event data",
    icon_url="/api/projects/@current/hog_functions/icon/?id=slack.com",
    hog="""
fetch("https://slack.com/api/chat.postMessage", {
  'body': {
    'channel': inputs.channel,
    'icon_emoji': inputs.icon_emoji,
    'username': inputs.username,
    'blocks': inputs.blocks,
    'text': inputs.text,
  },
  'method': 'POST',
  'headers': {
    'Authorization': f'Bearer {inputs.integration.access_token}',
    'Content-Type': 'application/json'
  }
});
""".strip(),
    inputs_schema=[
        {
            "key": "integration",
            "type": "integration",
            "label": "Slack workspace",
            "secret": False,
            "required": True,
            "integration": "slack",
        },
        {
            "key": "channel",
            "type": "string",
            "label": "Channel to post to",
            "description": "Select the channel to post to (e.g. #general). The PostHog app must be installed in the workspace.",
            "secret": False,
            "required": True,
        },
        {"key": "icon_emoji", "type": "string", "label": "Emoji icon", "default": ":hedgehog:", "required": False},
        {"key": "username", "type": "string", "label": "Bot name", "defaukt": "PostHog", "required": False},
        {
            "key": "blocks",
            "type": "json",
            "label": "Blocks",
            "description": "Blocks Slack (see https://api.slack.com/block-kit/building)",
            "default": [
                {
                    "text": {
                        "text": "*{person.name}* triggered event: '{event.name}'",
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
        },
        {"key": "text", "type": "string", "label": "Plain text message", "description": "Optional fallback message."},
    ],
)
