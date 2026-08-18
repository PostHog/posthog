from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="stable",
    free=True,
    type="destination",
    id="template-microsoft-teams",
    name="Microsoft Teams",
    description="Sends a message to a Microsoft Teams channel",
    icon_url="/static/services/microsoft-teams.png",
    category=["Customer Success"],
    code_language="hog",
    code="""
let validUrl := (
    match(inputs.webhookUrl, '^https://[^/]+.logic.azure.com(:443)?/workflows/[^/]+/triggers/[^/]+/paths/invoke?.*') or
    match(inputs.webhookUrl, '^https://[^/]+.webhook.office.com/webhookb2/[^/]+/IncomingWebhook/[^/]+/[^/]+') or
    match(inputs.webhookUrl, '^https://[^/]+.powerautomate.com/[^/]+') or
    match(inputs.webhookUrl, '^https://[^/]+.flow.microsoft.com/[^/]+') or
    match(inputs.webhookUrl, '^https://[^/]+.environment.api.powerplatform.com(:443)?/powerautomate/automations/direct/(.*/)?workflows/.*')
);

if (not validUrl) {
    let knownHost := match(inputs.webhookUrl, '^https://[^/]*(logic.azure.com|webhook.office.com|powerautomate.com|flow.microsoft.com|environment.api.powerplatform.com)');
    if (knownHost) {
        throw Error('We recognized the Microsoft Teams host, but not the URL path. Check that you copied the full webhook URL from Power Automate or Teams, including the path after the host.')
    }
    throw Error('Invalid URL. The URL should match either Azure Logic Apps format (https://<region>.logic.azure.com/workflows/...), Power Platform format (https://<tenant>.webhook.office.com/webhookb2/...), Power Automate format (https://<region>.powerautomate.com/... or https://<region>.flow.microsoft.com/...), or Power Platform environment format (https://<tenant>.environment.api.powerplatform.com/powerautomate/automations/direct/[<cluster>/]workflows/...)')
}

let res := fetch(inputs.webhookUrl, {
    'body': {
        'type': 'message',
        'attachments': [
            {
                'contentType': 'application/vnd.microsoft.card.adaptive',
                'contentUrl': null,
                'content': {
                    '$schema': 'http://adaptivecards.io/schemas/adaptive-card.json',
                    'type': 'AdaptiveCard',
                    'version': '1.2',
                    'body': [
                        {
                            'type': 'TextBlock',
                            'text': inputs.text,
                            'wrap': true
                        }
                    ]
                }
            }
        ]
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
            "description": "You can use any of these options: Azure Logic Apps (logic.azure.com), Power Platform webhooks (create through Microsoft Teams by adding an incoming webhook connector to your channel), Power Automate (powerautomate.com or flow.microsoft.com), or Power Platform environment endpoints (environment.api.powerplatform.com)",
            "secret": False,
            "required": True,
        },
        {
            "key": "text",
            "type": "string",
            "label": "Text",
            "description": "(see https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/add-incoming-webhook?tabs=newteams%2Cdotnet#example)",
            "default": "**{person.name}** triggered event: '{event.event}'",
            "secret": False,
            "required": True,
        },
    ],
)
