import {
    HogFunctionSubTemplateIdType,
    HogFunctionSubTemplateType,
    HogFunctionTemplateType,
    PropertyFilterType,
    PropertyOperator,
    SurveyEventName,
    SurveyEventProperties,
} from '~/types'

export const HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES: Record<
    HogFunctionSubTemplateIdType,
    Pick<HogFunctionSubTemplateType, 'sub_template_id' | 'type'> &
        Omit<Partial<HogFunctionSubTemplateType>, 'sub_template_id' | 'type'>
> = {
    'survey-response': {
        sub_template_id: 'survey-response',
        type: 'destination',
        filters: {
            events: [
                {
                    id: SurveyEventName.SENT,
                    type: 'events',
                    properties: [
                        {
                            key: SurveyEventProperties.SURVEY_RESPONSE,
                            type: PropertyFilterType.Event,
                            value: 'is_set',
                            operator: PropertyOperator.IsSet,
                        },
                    ],
                },
            ],
        },
    },
    'early-access-feature-enrollment': {
        sub_template_id: 'early-access-feature-enrollment',
        type: 'destination',
        filters: { events: [{ id: '$feature_enrollment_update', type: 'events' }] },
    },
    'activity-log': {
        sub_template_id: 'activity-log',
        type: 'internal_destination',
        filters: { events: [{ id: '$activity_log_entry_created', type: 'events' }] },
    },
    'error-tracking-issue-created': {
        sub_template_id: 'error-tracking-issue-created',
        type: 'internal_destination',
        filters: { events: [{ id: '$error_tracking_issue_created', type: 'events' }] },
    },
    'error-tracking-issue-reopened': {
        sub_template_id: 'error-tracking-issue-reopened',
        type: 'internal_destination',
        filters: { events: [{ id: '$error_tracking_issue_reopened', type: 'events' }] },
    },
}

export const HOG_FUNCTION_SUB_TEMPLATES: Record<HogFunctionSubTemplateIdType, HogFunctionSubTemplateType[]> = {
    'survey-response': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['survey-response'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on survey response',
            description: 'Send a webhook when a survey response is submitted',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['survey-response'],
            template_id: 'template-discord',
            name: 'Post to Discord on survey response',
            description: 'Posts a message to Discord when a user responds to a survey',
            inputs: {
                content: {
                    value: '**{person.name}** responded to survey **{event.properties.$survey_name}**',
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['survey-response'],
            template_id: 'template-microsoft-teams',
            name: 'Post to Microsoft Teams on survey response',
            description: 'Posts a message to Microsoft Teams when a user responds to a survey',
            inputs: {
                text: {
                    value: '**{person.name}** responded to survey **{event.properties.$survey_name}**',
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['survey-response'],
            template_id: 'template-slack',
            name: 'Post to Slack on survey response',
            description: 'Posts a message to Slack when a user responds to a survey',
            inputs: {
                blocks: {
                    value: [
                        {
                            text: {
                                text: '*{person.name}* responded to survey *{event.properties.$survey_name}*',
                                type: 'mrkdwn',
                            },
                            type: 'section',
                        },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}/surveys/{event.properties.$survey_id}',
                                    text: { text: 'View Survey', type: 'plain_text' },
                                    type: 'button',
                                },
                                {
                                    url: '{person.url}',
                                    text: { text: 'View Person', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: '*{person.name}* responded to survey *{event.properties.$survey_name}*',
                },
            },
        },
    ],
    'early-access-feature-enrollment': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['early-access-feature-enrollment'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on feature enrollment',
            description: 'Send a webhook when a user enrolls or un-enrolls in an early access feature',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['early-access-feature-enrollment'],
            template_id: 'template-discord',
            name: 'Post to Discord on feature enrollment',
            description: 'Posts a message to Discord when a user enrolls or un-enrolls in an early access feature',
            inputs: {
                content: {
                    value: `**{person.name}** {event.properties.$feature_enrollment ? 'enrolled in' : 'un-enrolled from'} the early access feature for '{event.properties.$feature_flag}'`,
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['early-access-feature-enrollment'],
            template_id: 'template-microsoft-teams',
            name: 'Post to Microsoft Teams on feature enrollment',
            description:
                'Posts a message to Microsoft Teams when a user enrolls or un-enrolls in an early access feature',
            inputs: {
                text: {
                    value: `**{person.name}** {event.properties.$feature_enrollment ? 'enrolled in' : 'un-enrolled from'} the early access feature for '{event.properties.$feature_flag}'`,
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['early-access-feature-enrollment'],
            template_id: 'template-slack',
            name: 'Post to Slack on feature enrollment',
            description: 'Posts a message to Slack when a user enrolls or un-enrolls in an early access feature',
            inputs: {
                blocks: {
                    value: [
                        {
                            text: {
                                text: "*{person.name}* {event.properties.$feature_enrollment ? 'enrolled in' : 'un-enrolled from'} the early access feature for '{event.properties.$feature_flag}'",
                                type: 'mrkdwn',
                            },
                            type: 'section',
                        },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{person.url}',
                                    text: { text: 'View Person in PostHog', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: "*{person.name}* {event.properties.$feature_enrollment ? 'enrolled in' : 'un-enrolled from'} the early access feature for '{event.properties.$feature_flag}'",
                },
            },
        },
    ],
    'activity-log': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['activity-log'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on team activity',
            description: 'Send a webhook when a team activity occurs',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['activity-log'],
            template_id: 'template-discord',
            name: 'Post to Discord on team activity',
            description: 'Posts a message to Discord when a team activity occurs',
            inputs: {
                content: {
                    value: '**{person.name}** {event.properties.activity} {event.properties.scope} {event.properties.item_id}',
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['activity-log'],
            template_id: 'template-microsoft-teams',
            name: 'Post to Microsoft Teams on team activity',
            description: 'Posts a message to Microsoft Teams when a team activity occurs',
            inputs: {
                text: {
                    value: '**{person.name}** {event.properties.activity} {event.properties.scope} {event.properties.item_id}',
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['activity-log'],
            template_id: 'template-slack',
            name: 'Post to Slack on team activity',
            description: 'Posts a message to Slack when a team activity occurs',
            inputs: {
                blocks: {
                    value: [
                        {
                            text: {
                                text: '*{person.name}* {event.properties.activity} {event.properties.scope} {event.properties.item_id} ',
                                type: 'mrkdwn',
                            },
                            type: 'section',
                        },
                    ],
                },
                text: {
                    value: '*{person.name}* {event.properties.activity} {event.properties.scope} {event.properties.item_id}',
                },
            },
        },
    ],
    'error-tracking-issue-created': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-created'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on issue created',
            description: 'Send a webhook when an issue is created',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-created'],
            template_id: 'template-discord',
            name: 'Post to Discord on issue created',
            description: 'Posts a message to Discord when an issue is created',
            inputs: {
                content: {
                    value: '**🔴 {event.properties.name} created:** {event.properties.description}',
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-created'],
            template_id: 'template-microsoft-teams',
            name: 'Post to Microsoft Teams on issue created',
            description: 'Posts a message to Microsoft Teams when an issue is created',
            inputs: {
                text: {
                    value: '**🔴 {event.properties.name} created:** {event.properties.description} (View in [Posthog]({project.url}/error_tracking/{event.distinct_id}))',
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-created'],
            template_id: 'template-slack',
            name: 'Post to Slack on issue created',
            description: 'Posts a message to Slack when an issue is created',
            inputs: {
                blocks: {
                    value: [
                        { type: 'header', text: { type: 'plain_text', text: '🔴 {event.properties.name}' } },
                        { type: 'section', text: { type: 'plain_text', text: 'New issue created' } },
                        { type: 'section', text: { type: 'mrkdwn', text: '```{event.properties.description}```' } },
                        {
                            type: 'context',
                            elements: [
                                { type: 'plain_text', text: 'Status: {event.properties.status}' },
                                { type: 'mrkdwn', text: 'Project: <{project.url}|{project.name}>' },
                                { type: 'mrkdwn', text: 'Alert: <{source.url}|{source.name}>' },
                            ],
                        },
                        { type: 'divider' },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}/error_tracking/{event.distinct_id}',
                                    text: { text: 'View Issue', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: 'New issue created: {event.properties.name}',
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-created'],
            template_id: 'template-linear',
            name: 'Linear issue on issue created',
            description: 'Create an issue in Linear when an issue is created.',
        },
    ],
    'error-tracking-issue-reopened': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-reopened'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on issue reopened',
            description: 'Send a webhook when an issue is reopened',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-reopened'],
            template_id: 'template-discord',
            name: 'Post to Discord on issue reopened',
            description: 'Posts a message to Discord when an issue is reopened',
            inputs: {
                content: {
                    value: '**🔄 {event.properties.name} reopened:** {event.properties.description}',
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-reopened'],
            template_id: 'template-microsoft-teams',
            name: 'Post to Microsoft Teams on issue reopened',
            description: 'Posts a message to Microsoft Teams when an issue is reopened',
            inputs: {
                text: {
                    value: '**🔄 {event.properties.name} reopened:** {event.properties.description}',
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-reopened'],
            template_id: 'template-slack',
            name: 'Post to Slack on issue reopened',
            description: 'Posts a message to Slack when an issue is reopened',
            inputs: {
                blocks: {
                    value: [
                        { type: 'header', text: { type: 'plain_text', text: '🔄 {event.properties.name}' } },
                        { type: 'section', text: { type: 'plain_text', text: 'Issue reopened' } },
                        { type: 'section', text: { type: 'mrkdwn', text: '```{event.properties.description}```' } },
                        {
                            type: 'context',
                            elements: [
                                { type: 'plain_text', text: 'Status: {event.properties.status}' },
                                { type: 'mrkdwn', text: 'Project: <{project.url}|{project.name}>' },
                                { type: 'mrkdwn', text: 'Alert: <{source.url}|{source.name}>' },
                            ],
                        },
                        { type: 'divider' },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}/error_tracking/{event.distinct_id}',
                                    text: { text: 'View Issue', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: 'Issue reopened: {event.properties.name}',
                },
            },
        },
    ],
}

export const getSubTemplate = (
    template: HogFunctionTemplateType,
    subTemplateId: HogFunctionSubTemplateIdType
): HogFunctionSubTemplateType | null => {
    return HOG_FUNCTION_SUB_TEMPLATES[subTemplateId].find((x) => x.template_id === template.id) || null
}
