from posthog.cdp.templates.hog_function_template import HogFunctionTemplate, HogFunctionSubTemplate, SUB_TEMPLATE_COMMON

template: HogFunctionTemplate = HogFunctionTemplate(
    status="free",
    id="template-microsoft-teams",
    name="Microsoft Teams",
    description="Sends a message to a Microsoft Teams channel",
    icon_url="/static/services/microsoft-teams.png",
    category=["Customer Success"],
    hog="""
if (not match(inputs.webhookUrl, '^https://[^/]+.webhook.office.com/webhookb2/.*')) {
    throw Error('Invalid url');
}

let res := fetch(inputs.webhookUrl, {
    'body': {
        'text': inputs.content
    },
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json'
    }
});

if (res.status >= 400) {
    throw Error(f'Failed to post message to Microsoft Teams: {res.status}: {res.body}');
}
""".strip(),
    inputs_schema=[
        {
            "key": "webhookUrl",
            "type": "string",
            "label": "Webhook URL",
            "description": "See this page on how to generate a Webhook URL: https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/add-incoming-webhook?tabs=newteams%2Cdotnet#create-an-incoming-webhook",
            "secret": False,
            "required": True,
        },
        {
            "key": "content",
            "type": "string",
            "label": "Content",
            "description": "(see https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/add-incoming-webhook?tabs=newteams%2Cdotnet#example)",
            "default": "**{person.name}** triggered event: '{event.event}'",
            "secret": False,
            "required": True,
        },
    ],
    sub_templates=[
        HogFunctionSubTemplate(
            id="early_access_feature_enrollment",
            name="Post to Microsoft Teams on feature enrollment",
            description="Posts a message to Microsoft Teams when a user enrolls or un-enrolls in an early access feature",
            filters=SUB_TEMPLATE_COMMON["early_access_feature_enrollment"].filters,
            inputs={
                "content": "**{person.name}** {event.properties.$feature_enrollment ? 'enrolled in' : 'un-enrolled from'} the early access feature for '{event.properties.$feature_flag}'"
            },
        ),
        HogFunctionSubTemplate(
            id="survey_response",
            name="Post to Microsoft Teams on survey response",
            description="Posts a message to Microsoft Teams when a user responds to a survey",
            filters=SUB_TEMPLATE_COMMON["survey_response"].filters,
            inputs={"content": "**{person.name}** responded to survey **{event.properties.$survey_name}**"},
        ),
    ],
)
