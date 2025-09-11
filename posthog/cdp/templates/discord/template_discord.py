from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

COMMON_INPUTS_SCHEMA = [
    {
        "key": "webhookUrl",
        "type": "string",
        "label": "Webhook URL",
        "description": "See this page on how to generate a Webhook URL: https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks",
        "secret": False,
        "required": True,
    },
]

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="stable",
    free=True,
    type="destination",
    id="template-discord",
    name="Discord",
    description="Sends a message to a discord channel",
    icon_url="/static/services/discord.png",
    category=["Customer Success"],
    code_language="hog",
    code="""
if (not match(inputs.webhookUrl, '^https://discord.com/api/webhooks/.*')) {
    throw Error('Invalid URL. The URL should match the format: https://discord.com/api/webhooks/...')
}

let res := fetch(inputs.webhookUrl, {
    'body': {
        'content': inputs.content
    },
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json'
    }
});

if (res.status >= 400) {
    throw Error(f'Failed to post message to Discord: {res.status}: {res.body}');
}
""".strip(),
    inputs_schema=[
        {
            "key": "webhookUrl",
            "type": "string",
            "label": "Webhook URL",
            "description": "See this page on how to generate a Webhook URL: https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks",
            "secret": False,
            "required": True,
        },
        {
            "key": "content",
            "type": "string",
            "label": "Content",
            "description": "(see https://support.discord.com/hc/en-us/articles/210298617-Markdown-Text-101-Chat-Formatting-Bold-Italic-Underline)",
            "default": "**{person.name}** triggered event: '{event.event}'",
            "secret": False,
            "required": True,
        },
    ],
)
