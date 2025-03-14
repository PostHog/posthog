import { actions, kea, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { urlToAction } from 'kea-router'

import type { onboardingErrorTrackingAlertsLogicType } from './onboardingErrorTrackingAlertsLogicType'

export type ErrorTrackingAlertIntegrationType = 'slack' | 'teams' | 'discord'

export const onboardingErrorTrackingAlertsLogic = kea<onboardingErrorTrackingAlertsLogicType>([
    path(['scenes', 'onboarding', 'error-tracking', 'onboardingErrorTrackingAlertsLogic']),
    actions({
        setIntegration: (integration: ErrorTrackingAlertIntegrationType | null) => ({ integration }),
        createDefaultAlerts: () => ({}),
    }),
    reducers({
        integration: [
            null as ErrorTrackingAlertIntegrationType | null,
            {
                setIntegration: (_, { integration }) => integration,
            },
        ],
    }),
    forms(({ values }) => ({
        connectionConfig: {
            defaults: {
                discordWebhookUrl: undefined,
                teamsWebhookUrl: undefined,
                slackChannelId: undefined,
            },

            errors: ({ discordWebhookUrl, teamsWebhookUrl, slackChannelId }) => {
                return {
                    discordWebhookUrl:
                        !values.integration === 'discord' && !discordWebhookUrl
                            ? 'Please enter a Discord webhook URL'
                            : undefined,
                    teamsWebhookUrl:
                        !values.integration === 'teams' && !teamsWebhookUrl
                            ? 'Please enter a Teams webhook URL'
                            : undefined,
                    slackChannelId:
                        !values.integration === 'slack' && !slackChannelId
                            ? 'Please choose a Slack channel'
                            : undefined,
                }
            },

            submit: async ({ id }) => {
                debugger
                // if (values.integration === 'discord') {
                //     actions.createDefaultAlerts()
                // } else if (values.integration === 'teams') {
                //     actions.createDefaultAlerts()
                // } else if (values.integration === 'slack') {
                //     actions.createDefaultAlerts()
                // }
            },
        },
    })),
    urlToAction(({}) => ({})),
])
