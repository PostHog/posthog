from posthog.cdp.templates.hog_function_template import HogFunctionTemplate, HogFunctionSubTemplate, SUB_TEMPLATE_COMMON

template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-discord",
    name="Discord",
    description="Sends a message to a discord channel",
    icon_url="/static/services/discord.png",
    category=["Customer Success"],
    hog="""
let res := fetch(inputs.webhookUrl, {
    'body': inputs.content,
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json'
    }
});

if (res.status != 200 or not res.body.ok) {
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
            "type": "json",
            "label": "Content",
            "description": "(see https://support.discord.com/hc/en-us/articles/210298617-Markdown-Text-101-Chat-Formatting-Bold-Italic-Underline)",
            "default": {"content": "**{person.name}** triggered event: '{event.event}'"},
            "secret": False,
            "required": True,
        },
    ],
    sub_templates=[
        HogFunctionSubTemplate(
            id="early_access_feature_enrollment",
            name="Post to Discord on feature enrollment",
            description="Posts a message to Discord when a user enrolls or un-enrolls in an early access feature",
            filters=SUB_TEMPLATE_COMMON["early_access_feature_enrollment"].filters,
            inputs={
                "content": {
                    "content": "**{person.name}** {event.properties.$feature_enrollment ? 'enrolled in' : 'un-enrolled from'} the early access feature for '{event.properties.$feature_flag}'"
                },
            },
        ),
        HogFunctionSubTemplate(
            id="survey_response",
            name="Post to Discord on survey response",
            description="Posts a message to Discord when a user responds to a survey",
            filters=SUB_TEMPLATE_COMMON["survey_response"].filters,
            inputs={
                "content": {"content": "**{person.name}** responded to survey **{event.properties.$survey_name}**"},
            },
        ),
    ],
)
