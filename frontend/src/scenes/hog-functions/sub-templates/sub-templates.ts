import { FEATURE_FLAGS, INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID } from 'lib/constants'

import {
    HogFunctionConfigurationContextId,
    HogFunctionSubTemplateIdType,
    HogFunctionSubTemplateType,
    HogFunctionTemplateType,
    PropertyFilterType,
    PropertyOperator,
    SurveyEventName,
} from '~/types'

export const HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES: Record<
    HogFunctionSubTemplateIdType,
    Pick<HogFunctionSubTemplateType, 'sub_template_id' | 'type' | 'context_id'> &
        Omit<Partial<HogFunctionSubTemplateType>, 'sub_template_id' | 'type' | 'context_id'>
> = {
    'survey-response': {
        sub_template_id: 'survey-response',
        context_id: 'standard',
        type: 'destination',
        filters: {
            events: [
                {
                    id: SurveyEventName.SENT,
                    type: 'events',
                },
                {
                    id: SurveyEventName.DISMISSED,
                    type: 'events',
                },
            ],
        },
    },
    'early-access-feature-enrollment': {
        sub_template_id: 'early-access-feature-enrollment',
        type: 'destination',
        context_id: 'standard',
        filters: { events: [{ id: '$feature_enrollment_update', type: 'events' }] },
    },
    'activity-log': {
        sub_template_id: 'activity-log',
        type: 'internal_destination',
        context_id: 'activity-log',
        filters: { events: [{ id: '$activity_log_entry_created', type: 'events' }] },
    },
    'feature-flag-change': {
        sub_template_id: 'feature-flag-change',
        type: 'internal_destination',
        context_id: 'activity-log',
        filters: {
            events: [
                {
                    id: '$activity_log_entry_created',
                    type: 'events',
                    properties: [
                        {
                            key: 'scope',
                            type: PropertyFilterType.Event,
                            value: ['FeatureFlag'],
                            operator: PropertyOperator.Exact,
                        },
                    ],
                },
            ],
        },
    },
    'discussion-mention': {
        sub_template_id: 'discussion-mention',
        type: 'internal_destination',
        context_id: 'discussion-mention',
        filters: { events: [{ id: '$discussion_mention_created', type: 'events' }] },
    },
    'error-tracking-issue-created': {
        sub_template_id: 'error-tracking-issue-created',
        type: 'internal_destination',
        context_id: 'error-tracking',
        filters: { events: [{ id: '$error_tracking_issue_created', type: 'events' }] },
    },
    'error-tracking-issue-reopened': {
        sub_template_id: 'error-tracking-issue-reopened',
        type: 'internal_destination',
        context_id: 'error-tracking',
        filters: { events: [{ id: '$error_tracking_issue_reopened', type: 'events' }] },
    },
    'error-tracking-issue-spiking': {
        sub_template_id: 'error-tracking-issue-spiking',
        type: 'internal_destination',
        context_id: 'error-tracking',
        filters: { events: [{ id: '$error_tracking_issue_spiking', type: 'events' }] },
    },
    [INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID]: {
        sub_template_id: INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID,
        type: 'internal_destination',
        context_id: 'insight-alerts',
        filters: { events: [{ id: '$insight_alert_firing', type: 'events' }] },
    },
    'experiment-significant': {
        sub_template_id: 'experiment-significant',
        type: 'internal_destination',
        context_id: 'experiment-alerts',
        filters: { events: [{ id: '$experiment_metric_significant', type: 'events' }] },
    },
    'logs-alert-firing': {
        sub_template_id: 'logs-alert-firing',
        type: 'internal_destination',
        context_id: 'logs-alerting',
        filters: { events: [{ id: '$logs_alert_firing', type: 'events' }] },
        flag: FEATURE_FLAGS.LOGS_ALERTING,
    },
    'logs-alert-resolved': {
        sub_template_id: 'logs-alert-resolved',
        type: 'internal_destination',
        context_id: 'logs-alerting',
        filters: { events: [{ id: '$logs_alert_resolved', type: 'events' }] },
        flag: FEATURE_FLAGS.LOGS_ALERTING,
    },
    'logs-alert-auto-disabled': {
        sub_template_id: 'logs-alert-auto-disabled',
        type: 'internal_destination',
        context_id: 'logs-alerting',
        filters: { events: [{ id: '$logs_alert_auto_disabled', type: 'events' }] },
        flag: FEATURE_FLAGS.LOGS_ALERTING,
    },
    'logs-alert-errored': {
        sub_template_id: 'logs-alert-errored',
        type: 'internal_destination',
        context_id: 'logs-alerting',
        filters: { events: [{ id: '$logs_alert_errored', type: 'events' }] },
        flag: FEATURE_FLAGS.LOGS_ALERTING,
    },
    'health-check-firing': {
        sub_template_id: 'health-check-firing',
        type: 'internal_destination',
        context_id: 'health-alerts',
        filters: { events: [{ id: '$health_check_issue_firing', type: 'events' }] },
    },
    'health-check-resolved': {
        sub_template_id: 'health-check-resolved',
        type: 'internal_destination',
        context_id: 'health-alerts',
        filters: { events: [{ id: '$health_check_issue_resolved', type: 'events' }] },
    },
}

const FLAG_ACTOR_NAME = "{event.properties.user.first_name ? event.properties.user.first_name : 'PostHog'}"

function buildFlagChangeVerbPhrase(): string {
    const activity = 'event.properties.activity'
    const change = 'event.properties.detail.changes[1]'
    const afterGroups = `length(ifNull(${change}.after.groups, []))`
    const beforeGroups = `length(ifNull(${change}.before.groups, []))`

    const activeFieldVerb = `${change}.after == 'true' ? 'enabled' : 'disabled'`

    const filtersFieldVerb = [
        `${change}.after.multivariate != null ? 'updated variant rollout for'`,
        `${afterGroups} > ${beforeGroups} ? 'added a release condition to'`,
        `${afterGroups} < ${beforeGroups} ? 'removed a release condition from'`,
        `'updated release conditions on'`,
    ].join(' : ')

    const verbPhrase = [
        `${activity} == 'created' ? 'created'`,
        `${activity} == 'deleted' ? 'deleted'`,
        `${activity} == 'restored' ? 'restored'`,
        `${change}.field == 'active' ? (${activeFieldVerb})`,
        `${change}.field == 'filters' ? (${filtersFieldVerb})`,
        `'updated'`,
    ].join(' : ')

    return `{${verbPhrase}}`
}

const FLAG_CHANGE_VERB_PHRASE = buildFlagChangeVerbPhrase()

interface HealthAlertTemplateCopy {
    slackHeader: string
    slackBody: string
    webhookSummary: string
    discordContent: string
    teamsText: string
    actionButtonText: string
    namePrefix: string
    descriptionVerb: string
}

// Builds the destination variants for a health-alert sub-template. The body
// strings reference only the event envelope (title/summary/link/severity/kind),
// so adding a new health-check kind requires no changes here.
function buildHealthAlertSubTemplates(
    subTemplateId: 'health-check-firing' | 'health-check-resolved',
    copy: HealthAlertTemplateCopy
): HogFunctionSubTemplateType[] {
    const common = HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[subTemplateId]
    return [
        {
            ...common,
            template_id: 'template-webhook',
            name: `HTTP webhook when a ${copy.namePrefix}`,
            description: `Send a webhook when a health check ${copy.descriptionVerb}`,
            inputs: {
                body: {
                    value: {
                        summary: copy.webhookSummary,
                        title: '{event.properties.title}',
                        message: '{event.properties.summary}',
                        kind: '{event.properties.kind}',
                        severity: '{event.properties.severity}',
                        link: '{project.url}{event.properties.link}',
                        payload: '{event.properties.payload}',
                    },
                },
            },
        },
        {
            ...common,
            template_id: 'template-slack',
            name: `Post to Slack when a ${copy.namePrefix}`,
            description: `Post to a Slack channel when a health check ${copy.descriptionVerb}`,
            inputs: {
                blocks: {
                    value: [
                        { type: 'header', text: { type: 'plain_text', text: copy.slackHeader } },
                        { type: 'section', text: { type: 'mrkdwn', text: copy.slackBody } },
                        {
                            type: 'context',
                            elements: [
                                {
                                    type: 'mrkdwn',
                                    text: 'Severity: {event.properties.severity} · Project: <{project.url}|{project.name}>',
                                },
                            ],
                        },
                        { type: 'divider' },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}{event.properties.link}',
                                    text: { text: copy.actionButtonText, type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: { value: copy.webhookSummary },
            },
        },
        {
            ...common,
            template_id: 'template-discord',
            name: `Post to Discord when a ${copy.namePrefix}`,
            description: `Post to a Discord channel when a health check ${copy.descriptionVerb}`,
            inputs: { content: { value: copy.discordContent } },
        },
        {
            ...common,
            template_id: 'template-microsoft-teams',
            name: `Post to Microsoft Teams when a ${copy.namePrefix}`,
            description: `Post to a Microsoft Teams channel when a health check ${copy.descriptionVerb}`,
            inputs: { text: { value: copy.teamsText } },
        },
    ]
}

export const HOG_FUNCTION_SUB_TEMPLATES: Record<HogFunctionSubTemplateIdType, HogFunctionSubTemplateType[]> = {
    'survey-response': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['survey-response'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on survey response',
            description: 'Send a webhook when a survey is completed or dismissed',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['survey-response'],
            template_id: 'template-discord',
            name: 'Post to Discord on survey response',
            description: 'Posts a message to Discord when a survey is completed or dismissed',
            inputs: {
                content: {
                    value: "**{person.name}** {event.event == 'survey dismissed' ? 'dismissed' : 'completed'} survey **{event.properties.$survey_name}**",
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['survey-response'],
            template_id: 'template-microsoft-teams',
            name: 'Post to Microsoft Teams on survey response',
            description: 'Posts a message to Microsoft Teams when a survey is completed or dismissed',
            inputs: {
                text: {
                    value: "**{person.name}** {event.event == 'survey dismissed' ? 'dismissed' : 'completed'} survey **{event.properties.$survey_name}**",
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['survey-response'],
            template_id: 'template-slack',
            name: 'Post to Slack on survey response',
            description: 'Posts a message to Slack when a survey is completed or dismissed',
            inputs: {
                blocks: {
                    value: [
                        {
                            text: {
                                text: "*{person.name}* {event.event == 'survey dismissed' ? 'dismissed' : 'completed'} survey *{event.properties.$survey_name}*",
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
                    value: "*{person.name}* {event.event == 'survey dismissed' ? 'dismissed' : 'completed'} survey *{event.properties.$survey_name}*",
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
            inputs: {
                content: {
                    value: "**{event.properties.user.first_name ? event.properties.user.first_name : 'PostHog'}** {event.properties.activity} {event.properties.scope} `{event.properties.item_id}`",
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['activity-log'],
            template_id: 'template-discord',
            name: 'Post to Discord on team activity',
            description: 'Posts a message to Discord when a team activity occurs',
            inputs: {
                content: {
                    value: "**{event.properties.user.first_name ? event.properties.user.first_name : 'PostHog'}** {event.properties.activity} {event.properties.scope} `{event.properties.item_id}`",
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['activity-log'],
            template_id: 'template-microsoft-teams',
            name: 'Post to Microsoft Teams on team activity',
            description: 'Posts a message to Microsoft Teams when a team activity occurs',
            inputs: {
                content: {
                    value: "**{event.properties.user.first_name ? event.properties.user.first_name : 'PostHog'}** {event.properties.activity} {event.properties.scope} `{event.properties.item_id}`",
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
                                text: "*{event.properties.user.first_name ? event.properties.user.first_name : 'PostHog'}* {event.properties.activity} {event.properties.scope} {event.properties.item_id}",
                                type: 'mrkdwn',
                            },
                            type: 'section',
                        },
                    ],
                },
                text: {
                    value: "*{event.properties.user.first_name ? event.properties.user.first_name : 'PostHog'}* {event.properties.activity} {event.properties.scope} {event.properties.item_id}",
                },
            },
        },
    ],
    'feature-flag-change': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['feature-flag-change'],
            template_id: 'template-webhook',
            name: 'Notify webhook for feature flag changes',
            description: 'Send a webhook when a feature flag is changed',
            inputs: {
                content: {
                    value: `**${FLAG_ACTOR_NAME}** ${FLAG_CHANGE_VERB_PHRASE} feature flag \`{event.properties.detail.name}\``,
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['feature-flag-change'],
            template_id: 'template-discord',
            name: 'Notify Discord for feature flag changes',
            description: 'Posts a message to Discord when a feature flag is changed',
            inputs: {
                content: {
                    value: `**${FLAG_ACTOR_NAME}** ${FLAG_CHANGE_VERB_PHRASE} feature flag \`{event.properties.detail.name}\``,
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['feature-flag-change'],
            template_id: 'template-microsoft-teams',
            name: 'Notify Microsoft Teams for feature flag changes',
            description: 'Posts a message to Microsoft Teams when a feature flag is changed',
            inputs: {
                content: {
                    value: `**${FLAG_ACTOR_NAME}** ${FLAG_CHANGE_VERB_PHRASE} feature flag \`{event.properties.detail.name}\``,
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['feature-flag-change'],
            template_id: 'template-slack',
            name: 'Notify Slack for feature flag changes',
            description: 'Posts a message to Slack when a feature flag is changed',
            inputs: {
                blocks: {
                    value: [
                        {
                            text: {
                                text: `*${FLAG_ACTOR_NAME}* ${FLAG_CHANGE_VERB_PHRASE} feature flag \`{event.properties.detail.name}\``,
                                type: 'mrkdwn',
                            },
                            type: 'section',
                        },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}/feature_flags/{event.properties.item_id}',
                                    text: { text: 'View feature flag', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: `*${FLAG_ACTOR_NAME}* ${FLAG_CHANGE_VERB_PHRASE} feature flag \`{event.properties.detail.name}\``,
                },
            },
        },
    ],
    'discussion-mention': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['discussion-mention'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on discussion mention',
            description: 'Send a webhook when someone mentions you in a discussion',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['discussion-mention'],
            template_id: 'template-discord',
            name: 'Post to Discord on discussion mention',
            description: 'Posts a message to Discord when someone mentions you in a discussion',
            inputs: {
                content: {
                    value: '**{event.properties.commenter_user_name}** mentioned you in {event.properties.scope} {event.properties.item_id}',
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['discussion-mention'],
            template_id: 'template-microsoft-teams',
            name: 'Post to Microsoft Teams on discussion mention',
            description: 'Posts a message to Microsoft Teams when someone mentions you in a discussion',
            inputs: {
                text: {
                    value: '**{event.properties.commenter_user_name}** mentioned you in {event.properties.scope} {event.properties.item_id}',
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['discussion-mention'],
            template_id: 'template-slack',
            name: 'Post to Slack on discussion mention',
            description: 'Posts a notification to a Slack channel when someone is mentioned in a discussion',
            inputs: {
                icon_emoji: {
                    value: ':speech_balloon:',
                },
                blocks: {
                    value: [
                        {
                            text: {
                                text: '*{event.properties.commenter_user_name}* mentioned *{event.properties.mentioned_user_name}* in a discussion',
                                type: 'mrkdwn',
                            },
                            type: 'section',
                        },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{event.properties.item_url}',
                                    text: { text: 'View Discussion', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: '{event.properties.commenter_user_name} mentioned {event.properties.mentioned_user_name} in a discussion',
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
                    value: '**🔴 {event.properties.name} created:** {event.properties.description}\n\n[View in PostHog]({project.url}/error_tracking/{encodeURLComponent(event.properties.fingerprint)}?timestamp={event.properties.exception_timestamp}&utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=discord)',
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
                    value: '**🔴 {event.properties.name} created:** {event.properties.description} (View in [PostHog]({project.url}/error_tracking/{encodeURLComponent(event.properties.fingerprint)}?timestamp={event.properties.exception_timestamp}&utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=microsoft_teams))',
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
                        {
                            type: 'section',
                            text: { type: 'mrkdwn', text: '```{substring(event.properties.description, 1, 150)}```' },
                        },
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
                                    url: '{project.url}/error_tracking/{encodeURLComponent(event.properties.fingerprint)}?timestamp={event.properties.exception_timestamp}&utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=slack',
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
            inputs: {
                title: {
                    value: '{event.properties.name}',
                },
                description: {
                    value: '{event.properties.description}',
                },
                posthog_issue_id: {
                    value: '{encodeURLComponent(event.properties.fingerprint)}',
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-created'],
            template_id: 'template-github',
            name: 'GitHub issue on issue created',
            description: 'Create an issue in GitHub when an issue is created.',
            inputs: {
                title: {
                    value: '{event.properties.name}',
                },
                description: {
                    value: '{event.properties.description}',
                },
                posthog_issue_id: {
                    value: '{encodeURLComponent(event.properties.fingerprint)}',
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-created'],
            template_id: 'template-gitlab',
            name: 'GitLab issue on issue created',
            description: 'Create an issue in GitLab when an issue is created.',
            inputs: {
                title: {
                    value: '{event.properties.name}',
                },
                description: {
                    value: '{event.properties.description}',
                },
                posthog_issue_id: {
                    value: '{encodeURLComponent(event.properties.fingerprint)}',
                },
            },
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
                    value: '**🔄 {event.properties.name} reopened:** {event.properties.description}\n\n[View in PostHog]({project.url}/error_tracking/{encodeURLComponent(event.properties.fingerprint)}?timestamp={event.properties.exception_timestamp}&utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=discord)',
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
                    value: '**🔄 {event.properties.name} reopened:** {event.properties.description} (View in [PostHog]({project.url}/error_tracking/{encodeURLComponent(event.properties.fingerprint)}?timestamp={event.properties.exception_timestamp}&utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=microsoft_teams))',
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
                        {
                            type: 'section',
                            text: { type: 'mrkdwn', text: '```{substring(event.properties.description, 1, 150)}```' },
                        },
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
                                    url: '{project.url}/error_tracking/{encodeURLComponent(event.properties.fingerprint)}?timestamp={event.properties.exception_timestamp}&utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=slack',
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
    'error-tracking-issue-spiking': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-spiking'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on issue spiking',
            description: 'Send a webhook when an issue is spiking',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-spiking'],
            template_id: 'template-discord',
            name: 'Post to Discord on issue spiking',
            description: 'Posts a message to Discord when an issue is spiking',
            inputs: {
                content: {
                    value: `**📈 Issue spiking**

\`\`\`
{event.properties.name}: {substring(event.properties.description, 1, 1000)}
\`\`\`
**Exceptions in last 5 minutes:** {event.properties.current_bucket_value} ({event.properties.computed_baseline > 0 ? concat(round(event.properties.current_bucket_value / event.properties.computed_baseline), 'x over baseline') : 'no baseline yet'})
**Project:** [{project.name}]({project.url})
**Alert:** [{source.name}]({source.url})

[View issue]({project.url}/error_tracking/{encodeURLComponent(event.properties.fingerprint ? event.properties.fingerprint : event.distinct_id)}?utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=discord)`,
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-spiking'],
            template_id: 'template-microsoft-teams',
            name: 'Post to Microsoft Teams on issue spiking',
            description: 'Posts a message to Microsoft Teams when an issue is spiking',
            inputs: {
                text: {
                    value: "**📈 Issue spiking: {event.properties.name}:** {event.properties.description}\n**Exceptions in last 5 minutes:** {event.properties.current_bucket_value} ({event.properties.computed_baseline > 0 ? concat(round(event.properties.current_bucket_value / event.properties.computed_baseline), 'x over baseline') : 'no baseline yet'}) (View in [PostHog]({project.url}/error_tracking/{encodeURLComponent(event.properties.fingerprint ? event.properties.fingerprint : event.distinct_id)}?utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=microsoft_teams))",
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-spiking'],
            template_id: 'template-slack',
            name: 'Post to Slack on issue spiking',
            description: 'Posts a message to Slack when an issue is spiking',
            inputs: {
                blocks: {
                    value: [
                        { type: 'header', text: { type: 'plain_text', text: '📈 Issue spiking' } },
                        {
                            type: 'section',
                            text: {
                                type: 'mrkdwn',
                                text: '```{event.properties.name}: {substring(event.properties.description, 1, 1000)}```',
                            },
                        },
                        {
                            type: 'context',
                            elements: [
                                {
                                    type: 'plain_text',
                                    text: "Exceptions in last 5 minutes: {event.properties.current_bucket_value} ({event.properties.computed_baseline > 0 ? concat(round(event.properties.current_bucket_value / event.properties.computed_baseline), 'x over baseline') : 'no baseline yet'})",
                                },
                                { type: 'mrkdwn', text: 'Project: <{project.url}|{project.name}>' },
                                { type: 'mrkdwn', text: 'Alert: <{source.url}|{source.name}>' },
                            ],
                        },
                        { type: 'divider' },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}/error_tracking/{encodeURLComponent(event.properties.fingerprint ? event.properties.fingerprint : event.distinct_id)}?utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=slack',
                                    text: { text: 'View Issue', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: 'Issue spiking: {event.properties.name}',
                },
            },
        },
    ],
    'experiment-significant': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['experiment-significant'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on experiment significance',
            description: 'Send a webhook when an experiment metric reaches significance',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['experiment-significant'],
            template_id: 'template-slack',
            name: 'Post to Slack on experiment significance',
            description: 'Post to a Slack channel when an experiment metric reaches significance',
            inputs: {
                blocks: {
                    value: [
                        {
                            type: 'header',
                            text: {
                                type: 'plain_text',
                                text: "\ud83e\uddea Experiment '{event.properties.experiment_name}' has reached significance",
                            },
                        },
                        {
                            type: 'section',
                            text: {
                                type: 'mrkdwn',
                                text: '*{event.properties.variant_key}* variant is winning on *{event.properties.metric_name}* {event.properties.relative_change}\nChance to win: *{event.properties.chance_to_win}* \u00b7 Goal: *{event.properties.goal_direction}*',
                            },
                        },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}{event.properties.experiment_url}',
                                    text: { text: 'View experiment', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                        {
                            type: 'context',
                            elements: [{ type: 'mrkdwn', text: '{project.name}' }],
                        },
                    ],
                },
                text: {
                    value: "Experiment '{event.properties.experiment_name}' has reached significance",
                },
            },
        },
    ],
    [INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID]: [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on insight alert firing',
            description: 'Send a webhook when this insight alert fires',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID],
            template_id: 'template-slack',
            name: 'Post to Slack on insight alert firing',
            description: 'Post to a Slack channel when this insight alert fires',
            inputs: {
                blocks: {
                    value: [
                        {
                            type: 'header',
                            text: {
                                type: 'plain_text',
                                text: "Alert '{event.properties.alert_name}' firing for insight '{event.properties.insight_name}'",
                            },
                        },
                        {
                            type: 'section',
                            text: {
                                type: 'plain_text',
                                text: '{event.properties.breaches}',
                            },
                        },
                        {
                            type: 'context',
                            elements: [{ type: 'mrkdwn', text: 'Project: <{project.url}|{project.name}>' }],
                        },
                        { type: 'divider' },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}/insights/{event.properties.insight_id}?utm_source=alert&utm_campaign=alert_check_firing&utm_medium=slack',
                                    text: { text: 'View Insight', type: 'plain_text' },
                                    type: 'button',
                                },
                                {
                                    url: '{project.url}/insights/{event.properties.insight_id}/alerts?alert_id={event.properties.alert_id}&utm_source=alert&utm_campaign=alert_check_firing&utm_medium=slack',
                                    text: { text: 'View Alert', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: 'Alert triggered: {event.properties.insight_name}',
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID],
            template_id: 'template-discord',
            name: 'Post to Discord on insight alert firing',
            description: 'Post to a Discord channel when this insight alert fires',
            inputs: {
                content: {
                    value: "**Alert '{event.properties.alert_name}' firing** for insight '{event.properties.insight_name}'\n{event.properties.breaches}\n{project.url}/insights/{event.properties.insight_id}/alerts?alert_id={event.properties.alert_id}",
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID],
            template_id: 'template-microsoft-teams',
            name: 'Post to Microsoft Teams on insight alert firing',
            description: 'Post to a Microsoft Teams channel when this insight alert fires',
            inputs: {
                text: {
                    value: "**Alert '{event.properties.alert_name}' firing** for insight '{event.properties.insight_name}'\n\n{event.properties.breaches}\n\n[View alert]({project.url}/insights/{event.properties.insight_id}/alerts?alert_id={event.properties.alert_id})",
                },
            },
        },
    ],
    'logs-alert-firing': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['logs-alert-firing'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on log alert firing',
            description: 'Send a webhook when a log alert fires',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['logs-alert-firing'],
            template_id: 'template-slack',
            name: 'Post to Slack on log alert firing',
            description: 'Post to a Slack channel when a log alert fires',
            inputs: {
                blocks: {
                    value: [
                        {
                            type: 'header',
                            text: {
                                type: 'plain_text',
                                text: "Log alert '{event.properties.alert_name}' is firing",
                            },
                        },
                        {
                            type: 'section',
                            text: {
                                type: 'mrkdwn',
                                text: '*Threshold breached:* {event.properties.threshold_count} logs in {event.properties.window_minutes}m (limit: {event.properties.threshold_operator} {event.properties.threshold_value})',
                            },
                        },
                        {
                            type: 'context',
                            elements: [{ type: 'mrkdwn', text: 'Project: <{project.url}|{project.name}>' }],
                        },
                        { type: 'divider' },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}/logs?{event.properties.logs_url_params}&utm_source=alert&utm_campaign=logs_alert&utm_medium=slack',
                                    text: { text: 'View logs', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: "Log alert '{event.properties.alert_name}' is firing",
                },
            },
        },
    ],
    'logs-alert-resolved': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['logs-alert-resolved'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on log alert resolved',
            description: 'Send a webhook when a log alert resolves',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['logs-alert-resolved'],
            template_id: 'template-slack',
            name: 'Post to Slack on log alert resolved',
            description: 'Post to a Slack channel when a log alert resolves',
            inputs: {
                blocks: {
                    value: [
                        {
                            type: 'header',
                            text: {
                                type: 'plain_text',
                                text: "Log alert '{event.properties.alert_name}' has resolved",
                            },
                        },
                        {
                            type: 'section',
                            text: {
                                type: 'mrkdwn',
                                text: '*Current count:* {event.properties.result_count} in {event.properties.window_minutes}m (threshold: {event.properties.threshold_operator} {event.properties.threshold_count})',
                            },
                        },
                        {
                            type: 'context',
                            elements: [{ type: 'mrkdwn', text: 'Project: <{project.url}|{project.name}>' }],
                        },
                        { type: 'divider' },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}/logs?{event.properties.logs_url_params}&utm_source=alert&utm_campaign=logs_alert&utm_medium=slack',
                                    text: { text: 'View logs', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: "Log alert '{event.properties.alert_name}' has resolved",
                },
            },
        },
    ],
    'logs-alert-auto-disabled': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['logs-alert-auto-disabled'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on log alert auto-disabled',
            description: 'Send a webhook when a log alert is auto-disabled due to repeated failures',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['logs-alert-auto-disabled'],
            template_id: 'template-slack',
            name: 'Post to Slack on log alert auto-disabled',
            description: 'Post to Slack when a log alert is auto-disabled due to repeated failures',
            inputs: {
                blocks: {
                    value: [
                        {
                            type: 'header',
                            text: {
                                type: 'plain_text',
                                text: "Log alert '{event.properties.alert_name}' was auto-disabled",
                            },
                        },
                        {
                            type: 'section',
                            text: {
                                type: 'mrkdwn',
                                text: '*Reason:* {event.properties.consecutive_failures} consecutive check failures.\n*Last error:* {event.properties.last_error_message}',
                            },
                        },
                        {
                            type: 'context',
                            elements: [{ type: 'mrkdwn', text: 'Project: <{project.url}|{project.name}>' }],
                        },
                        { type: 'divider' },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}/logs?alertId={event.properties.alert_id}&utm_source=alert&utm_campaign=logs_alert&utm_medium=slack',
                                    text: { text: 'View alert', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: "Log alert '{event.properties.alert_name}' was auto-disabled after {event.properties.consecutive_failures} consecutive failures",
                },
            },
        },
    ],
    'health-check-firing': buildHealthAlertSubTemplates('health-check-firing', {
        // Verbs/copy chosen so the same template body works for any health-check kind.
        slackHeader: '{event.properties.title}',
        slackBody: '{event.properties.summary}',
        webhookSummary: '{event.properties.title}: {event.properties.summary}',
        discordContent:
            '**🩺 PostHog health check**\n\n*{event.properties.title}*\n{event.properties.summary}\n\n[View in PostHog]({project.url}{event.properties.link})',
        teamsText:
            '**🩺 PostHog health check:** *{event.properties.title}* — {event.properties.summary} (View in [PostHog]({project.url}{event.properties.link}))',
        actionButtonText: 'View in PostHog',
        namePrefix: 'health check fires',
        descriptionVerb: 'fires',
    }),
    'health-check-resolved': buildHealthAlertSubTemplates('health-check-resolved', {
        slackHeader: 'Resolved: {event.properties.title}',
        slackBody: '{event.properties.summary}',
        webhookSummary: 'Resolved: {event.properties.title} — {event.properties.summary}',
        discordContent:
            '**✅ PostHog health check resolved**\n\n*{event.properties.title}*\n{event.properties.summary}\n\n[View in PostHog]({project.url}{event.properties.link})',
        teamsText:
            '**✅ Resolved:** *{event.properties.title}* — {event.properties.summary} (View in [PostHog]({project.url}{event.properties.link}))',
        actionButtonText: 'View in PostHog',
        namePrefix: 'health check resolves',
        descriptionVerb: 'resolves',
    }),
    'logs-alert-errored': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['logs-alert-errored'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on log alert evaluation error',
            description: 'Send a webhook when a log alert fails to evaluate',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['logs-alert-errored'],
            template_id: 'template-slack',
            name: 'Post to Slack on log alert evaluation error',
            description: 'Post to Slack when a log alert fails to evaluate',
            inputs: {
                blocks: {
                    value: [
                        {
                            type: 'header',
                            text: {
                                type: 'plain_text',
                                text: "Log alert '{event.properties.alert_name}' couldn't evaluate",
                            },
                        },
                        {
                            type: 'section',
                            text: {
                                type: 'mrkdwn',
                                text: '*Reason:* {event.properties.error_message}\n*Failure count:* {event.properties.consecutive_failures}',
                            },
                        },
                        {
                            type: 'context',
                            elements: [{ type: 'mrkdwn', text: 'Project: <{project.url}|{project.name}>' }],
                        },
                        { type: 'divider' },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}/logs?alertId={event.properties.alert_id}&utm_source=alert&utm_campaign=logs_alert&utm_medium=slack',
                                    text: { text: 'View alert', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: "Log alert '{event.properties.alert_name}' couldn't evaluate: {event.properties.error_message}",
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

export const eventToHogFunctionContextId = (event: string | undefined): HogFunctionConfigurationContextId => {
    switch (event) {
        case '$error_tracking_issue_created':
        case '$error_tracking_issue_reopened':
        case '$error_tracking_issue_spiking':
            return 'error-tracking'
        case '$insight_alert_firing':
            return 'insight-alerts'
        case '$experiment_metric_significant':
            return 'experiment-alerts'
        case '$activity_log_entry_created':
            return 'activity-log'
        case '$discussion_mention_created':
            return 'discussion-mention'
        case '$logs_alert_firing':
        case '$logs_alert_resolved':
        case '$logs_alert_auto_disabled':
        case '$logs_alert_errored':
            return 'logs-alerting'
        case '$health_check_issue_firing':
        case '$health_check_issue_resolved':
            return 'health-alerts'
        default:
            return 'standard'
    }
}
