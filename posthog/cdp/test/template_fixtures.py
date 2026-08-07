"""Template fixtures for tests that need a real destination template row in Postgres.

These templates live in the Node service now, which Python tests do not run. The content is
copied from the templates as they were when they moved, so anything asserting on it — API
round-trips, snapshots — keeps behaving the same.

Tests only need a realistic destination here; they are not asserting anything about Slack or
Microsoft Teams in particular.
"""

from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

slack_template: HogFunctionTemplateDC = HogFunctionTemplateDC(
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
            "description": "Select the channel to post to. Channel IDs (e.g. C0123ABC, returned by integrations-channels-retrieve) are preferred; #channel-name (e.g. #general) is also accepted. The PostHog app must be installed in the workspace. For private channels, the PostHog app must be a member of the channel.",
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

microsoft_teams_template: HogFunctionTemplateDC = HogFunctionTemplateDC(
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
if (not match(inputs.webhookUrl, '^https://[^/]+.logic.azure.com:443/workflows/[^/]+/triggers/manual/paths/invoke?.*') and
    not match(inputs.webhookUrl, '^https://[^/]+.webhook.office.com/webhookb2/[^/]+/IncomingWebhook/[^/]+/[^/]+') and
    not match(inputs.webhookUrl, '^https://[^/]+.powerautomate.com/[^/]+') and
    not match(inputs.webhookUrl, '^https://[^/]+.flow.microsoft.com/[^/]+') and
    not match(inputs.webhookUrl, '^https://[^/]+.environment.api.powerplatform.com(:443)?/powerautomate/automations/direct/(.*/)?workflows/.*')) {
    throw Error('Invalid URL. The URL should match either Azure Logic Apps format (https://<region>.logic.azure.com:443/workflows/...), Power Platform format (https://<tenant>.webhook.office.com/webhookb2/...), Power Automate format (https://<region>.powerautomate.com/... or https://<region>.flow.microsoft.com/...), or Power Platform environment format (https://<tenant>.environment.api.powerplatform.com:443/powerautomate/automations/direct/[<cluster>/]workflows/...)')
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

zapier_template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="stable",
    free=True,
    type="destination",
    id="template-zapier",
    name="Zapier",
    description="Trigger Zaps in Zapier based on PostHog events. NOTE: Typically this is created from within Zapier using the PostHog app there.",
    icon_url="/static/services/zapier.png",
    category=["Custom"],
    code_language="hog",
    code="""
let hook_path := inputs.hook;
let prefix := 'https://hooks.zapier.com/';
// Remove the prefix if it exists
if (position(hook_path, prefix) == 1) {
  hook_path := replaceOne(hook_path, prefix, '');
}

// Remove leading slash if present to avoid double slashes
if (position(hook_path, '/') == 1) {
  hook_path := replaceOne(hook_path, '/', '');
}

let res := fetch(f'https://hooks.zapier.com/{hook_path}', {
  'method': 'POST',
  'body': inputs.body
});

if (inputs.debug) {
  print('Response', res.status, res.body);
}

""".strip(),
    inputs_schema=[
        {
            "key": "hook",
            "type": "string",
            "label": "Zapier hook path",
            "description": "Your Zapier webhook URL or just the path. You can create your own or use our native Zapier integration https://zapier.com/apps/posthog/integrations",
            "secret": False,
            "required": True,
            "hidden": False,
        },
        {
            "key": "body",
            "type": "json",
            "label": "JSON Body",
            "default": {
                "hook": {
                    "id": "{source.url}",
                    "event": "{event}",
                    "target": "https://hooks.zapier.com",
                },
                "data": {
                    "eventUuid": "{event.uuid}",
                    "event": "{event.event}",
                    "teamId": "{project.id}",
                    "distinctId": "{event.distinct_id}",
                    "properties": "{event.properties}",
                    "elementsChain": "{event.elementsChain}",
                    "timestamp": "{event.timestamp}",
                    "person": {"uuid": "{person.id}", "properties": "{person.properties}"},
                },
            },
            "secret": False,
            "required": False,
            "hidden": False,
        },
        {
            "key": "debug",
            "type": "boolean",
            "label": "Log responses",
            "description": "Logs the response of http calls for debugging.",
            "secret": False,
            "required": False,
            "default": False,
            "hidden": False,
        },
    ],
)
