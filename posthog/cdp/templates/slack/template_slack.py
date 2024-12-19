from posthog.cdp.templates.hog_function_template import HogFunctionTemplate, HogFunctionSubTemplate, SUB_TEMPLATE_COMMON


# TODO: Make modifying the default inputs schema easier
COMMON_INPUTS_SCHEMA = [
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
]

template: HogFunctionTemplate = HogFunctionTemplate(
    status="free",
    type="destination",
    id="template-slack",
    name="Slack",
    description="Sends a message to a slack channel",
    icon_url="/static/services/slack.png",
    category=["Customer Success"],
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
        *COMMON_INPUTS_SCHEMA,
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
        },
        {
            "key": "text",
            "type": "string",
            "label": "Plain text message",
            "description": "Optional fallback message if blocks are not provided or supported",
            "default": "*{person.name}* triggered event: '{event.event}'",
            "secret": False,
            "required": False,
        },
    ],
    sub_templates=[
        HogFunctionSubTemplate(
            id="early-access-feature-enrollment",
            name="Post to Slack on feature enrollment",
            description="Posts a message to Slack when a user enrolls or un-enrolls in an early access feature",
            filters=SUB_TEMPLATE_COMMON["early-access-feature-enrollment"].filters,
            inputs_schema=[
                *COMMON_INPUTS_SCHEMA,
                {
                    "key": "blocks",
                    "type": "json",
                    "label": "Blocks",
                    "description": "(see https://api.slack.com/block-kit/building)",
                    "default": [
                        {
                            "text": {
                                "text": "*{person.name}* {event.properties.$feature_enrollment ? 'enrolled in' : 'un-enrolled from'} the early access feature for '{event.properties.$feature_flag}'",
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
                            ],
                        },
                    ],
                    "secret": False,
                    "required": False,
                },
                {
                    "key": "text",
                    "type": "string",
                    "label": "Plain text message",
                    "description": "Optional fallback message if blocks are not provided or supported",
                    "default": "*{person.name}* {event.properties.$feature_enrollment ? 'enrolled in' : 'un-enrolled from'} the early access feature for '{event.properties.$feature_flag}'",
                    "secret": False,
                    "required": False,
                },
            ],
        ),
        HogFunctionSubTemplate(
            id="survey-response",
            name="Post to Slack on survey response",
            description="Posts a message to Slack when a user responds to a survey",
            filters=SUB_TEMPLATE_COMMON["survey-response"].filters,
            inputs_schema=[
                *COMMON_INPUTS_SCHEMA,
                {
                    "key": "blocks",
                    "type": "json",
                    "label": "Blocks",
                    "description": "(see https://api.slack.com/block-kit/building)",
                    "default": [
                        {
                            "text": {
                                "text": "*{person.name}* responded to survey *{event.properties.$survey_name}*",
                                "type": "mrkdwn",
                            },
                            "type": "section",
                        },
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "url": "{project.url}/surveys/{event.properties.$survey_id}",
                                    "text": {"text": "View Survey", "type": "plain_text"},
                                    "type": "button",
                                },
                                {
                                    "url": "{person.url}",
                                    "text": {"text": "View Person", "type": "plain_text"},
                                    "type": "button",
                                },
                            ],
                        },
                    ],
                    "secret": False,
                    "required": False,
                },
                {
                    "key": "text",
                    "type": "string",
                    "label": "Plain text message",
                    "description": "Optional fallback message if blocks are not provided or supported",
                    "default": "*{person.name}* responded to survey *{event.properties.$survey_name}*",
                    "secret": False,
                    "required": False,
                },
            ],
        ),
        HogFunctionSubTemplate(
            id="activity-log",
            name="Post to Slack on team activity",
            description="",
            filters=SUB_TEMPLATE_COMMON["activity-log"].filters,
            type="internal_destination",
            inputs_schema=[
                *COMMON_INPUTS_SCHEMA,
                {
                    "key": "blocks",
                    "type": "json",
                    "label": "Blocks",
                    "description": "(see https://api.slack.com/block-kit/building)",
                    "default": [
                        {
                            "text": {
                                "text": "*{person.properties.email}* {event.properties.activity} {event.properties.scope} {event.properties.item_id} ",
                                "type": "mrkdwn",
                            },
                            "type": "section",
                        }
                    ],
                    "secret": False,
                    "required": False,
                },
                {
                    "key": "text",
                    "type": "string",
                    "label": "Plain text message",
                    "description": "Optional fallback message if blocks are not provided or supported",
                    "default": "*{person.properties.email}* {event.properties.activity} {event.properties.scope} {event.properties.item_id}",
                    "secret": False,
                    "required": False,
                },
            ],
        ),
    ],
)
