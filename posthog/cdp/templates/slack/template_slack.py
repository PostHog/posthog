from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

# NOTE: Slack template is essentially just a webhook template with limited options

template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    id="template-slack",
    name="Slack webhook",
    description="Sends a webhook templated by the incoming event data",
    icon_url="/api/projects/@current/hog_functions/icon/?id=slack.com",
    hog="""
fetch(inputs.url, {
  'body': inputs.body,
  'method': 'POST',
  'headers': {
    'Content-Type': 'application/json'
  }
});
""".strip(),
    inputs_schema=[
        {
            "key": "url",
            "type": "string",
            "label": "Slack webhook URL",
            "description": "Create a slack webhook URL in your (see https://api.slack.com/messaging/webhooks)",
            "placeholder": "https://hooks.slack.com/services/XXX/YYY",
            "secret": False,
            "required": True,
        },
        {
            "key": "body",
            "type": "json",
            "label": "Message",
            "description": "Message to send to Slack (see https://api.slack.com/block-kit/building)",
            "default": {
                "blocks": [
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
                ]
            },
            "secret": False,
            "required": False,
        },
    ],
)
