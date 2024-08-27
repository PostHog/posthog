from posthog.cdp.templates.hog_function_template import HogFunctionTemplate, HogFunctionSubTemplate

template: HogFunctionTemplate = HogFunctionTemplate(
    status="free",
    id="template-slack",
    name="Post a Slack message",
    description="Sends a message to a slack channel",
    icon_url="/static/services/slack.png",
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

if (res.status != 200 or not res.body.ok) {
  print('Non-ok response:', res)
}
""".strip(),
    inputs_schema=[
        {
            "key": "slack_workspace",
            "type": "integration",
            "integration": "slack",
            "label": "Slack workspace",
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
        {
            "key": "blocks",
            "type": "json",
            "label": "Blocks",
            "description": "(see https://api.slack.com/block-kit/building)",
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
        {
            "key": "text",
            "type": "string",
            "label": "Plain text message",
            "description": "Optional fallback message if blocks are not provided or supported",
            "secret": False,
            "required": False,
        },
    ],
    sub_templates=[
        HogFunctionSubTemplate(
            id="early_access_feature_enrollment",
            name="Post to Slack on feature enrollment",
            description="Posts a message to Slack when a user enrolls or un-enrolls in an early access feature",
            filters={"events": [{"id": "$feature_enrollment_update", "type": "events"}]},
            inputs={
                "text": "*{person.name}* {event.properties.$feature_enrollment ? 'enrolled in' : 'un-enrolled from'} the early access feature for '{event.properties.$feature_flag}'",
                "blocks": [
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
                            # NOTE: It would be nice to have a link to the EAF but the event needs more info
                        ],
                    },
                ],
            },
        ),
        HogFunctionSubTemplate(
            id="survey_response",
            name="Post to Slack on survey response",
            description="Posts a message to Slack when a user responds to a survey",
            filters={
                "events": [
                    {
                        "id": "survey sent",
                        "type": "events",
                        "properties": [
                            {
                                "key": "$survey_response",
                                "type": "event",
                                "value": "is_set",
                                "operator": "is_set",
                            },
                        ],
                    }
                ]
            },
            inputs={
                "text": "*{person.name}* responded to survey *{event.properties.$survey_name}*",
                "blocks": [
                    {
                        "text": {
                            # TODO: Add the actual responses as well...
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
            },
        ),
    ],
)
