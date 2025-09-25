import { actions, afterMount, connect, kea, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { router } from 'kea-router'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { HogFunctionConfigurationType } from '~/types'

import { onboardingLogic } from '../onboardingLogic'
import type { onboardingErrorTrackingAlertsLogicType } from './onboardingErrorTrackingAlertsLogicType'

export type ErrorTrackingAlertIntegrationType = 'slack' | 'microsoft-teams' | 'discord'

const DEFAULT_HOG_FUNCTION_CONFIGURATION: Partial<HogFunctionConfigurationType> = {
    type: 'internal_destination',
    filters: { events: [{ id: '$error_tracking_issue_created', type: 'events' }] },
    enabled: true,
    masking: null,
}

const DEFAULT_SLACK_INPUTS: Record<string, any> = {
    icon_emoji: { value: ':hedgehog:' },
    username: { value: 'PostHog' },
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
                    {
                        type: 'mrkdwn',
                        text: 'Alert: <{source.url}|{source.name}>',
                    },
                ],
            },
            { type: 'divider' },
            {
                type: 'actions',
                elements: [
                    {
                        url: '{project.url}/error_tracking/{event.distinct_id}?fingerprint={event.properties.fingerprint}',
                        text: { text: 'View Issue', type: 'plain_text' },
                        type: 'button',
                    },
                ],
            },
        ],
    },
    text: { value: 'New issue created: {event.properties.name}' },
}

export const onboardingErrorTrackingAlertsLogic = kea<onboardingErrorTrackingAlertsLogicType>([
    path(['scenes', 'onboarding', 'error-tracking', 'onboardingErrorTrackingAlertsLogic']),
    connect(() => ({
        values: [integrationsLogic, ['slackIntegrations', 'slackAvailable']],
        actions: [onboardingLogic, ['goToNextStep']],
    })),
    actions({
        setIntegration: (integration: ErrorTrackingAlertIntegrationType | null) => ({ integration }),
    }),
    reducers({
        integration: [
            null as ErrorTrackingAlertIntegrationType | null,
            {
                setIntegration: (_, { integration }) => integration,
            },
        ],
    }),
    forms(({ values, actions }) => ({
        connectionConfig: {
            defaults: {
                discordWebhookUrl: undefined as string | undefined,
                microsoftTeamsWebhookUrl: undefined as string | undefined,
                slackWorkspaceId: undefined as number | undefined,
                slackChannelId: undefined as string | undefined,
            },

            errors: ({ discordWebhookUrl, microsoftTeamsWebhookUrl, slackChannelId }) => {
                return {
                    discordWebhookUrl:
                        values.integration === 'discord' && !discordWebhookUrl
                            ? 'Please enter a Discord webhook URL'
                            : undefined,
                    microsoftTeamsWebhookUrl:
                        values.integration === 'microsoft-teams' && !microsoftTeamsWebhookUrl
                            ? 'Please enter a Microsoft Teams webhook URL'
                            : undefined,
                    slackChannelId:
                        values.integration === 'slack' && !slackChannelId ? 'Please choose a Slack channel' : undefined,
                }
            },

            submit: async (formValues) => {
                const configuration = {
                    ...DEFAULT_HOG_FUNCTION_CONFIGURATION,
                    template_id: `template-${values.integration}-error-tracking-issue-created`,
                }

                if (values.integration === 'microsoft-teams') {
                    configuration.inputs = {
                        webhookUrl: { value: formValues.microsoftTeamsWebhookUrl },
                        text: { value: '**🔴 {event.properties.name} created:** {event.properties.description}' },
                    }
                } else if (values.integration === 'discord') {
                    configuration.inputs = {
                        webhookUrl: { value: formValues.discordWebhookUrl },
                        content: { value: '**🔴 {event.properties.name} created:** {event.properties.description}' },
                    }
                } else if (values.integration === 'slack') {
                    configuration.inputs = {
                        ...DEFAULT_SLACK_INPUTS,
                        slack_workspace: { value: formValues.slackWorkspaceId },
                        channel: { value: formValues.slackChannelId },
                    }
                }

                await api.hogFunctions.create(configuration)
                actions.goToNextStep()
            },
        },
    })),
    afterMount(({ actions }) => {
        const { kind, integration_id } = router.values.searchParams

        if (kind && kind === 'slack_callback') {
            actions.setIntegration('slack')

            if (integration_id) {
                actions.setConnectionConfigValue('slackWorkspaceId', integration_id)
            }
        }
    }),
])
