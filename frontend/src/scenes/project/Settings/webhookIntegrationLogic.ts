import { kea } from 'kea'
import api from 'lib/api'
import { lemonToast } from 'lib/components/lemonToast'
import { capitalizeFirstLetter } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import type { webhookIntegrationLogicType } from './webhookIntegrationLogicType'

function adjustDiscordWebhook(webhookUrl: string): string {
    // We need Discord webhook URLs to end with /slack for proper handling, this ensures that
    return webhookUrl.replace(/\/*(?:posthog|slack)?\/?$/, '/slack')
}

export const webhookIntegrationLogic = kea<webhookIntegrationLogicType>({
    path: ['scenes', 'project', 'Settings', 'webhookIntegrationLogic'],
    loaders: ({ actions }) => ({
        testedWebhook: [
            null as string | null,
            {
                testWebhook: async (webhook: string) => {
                    if (webhook?.includes('discord.com/')) {
                        webhook = adjustDiscordWebhook(webhook)
                    }

                    if (webhook) {
                        try {
                            const response = await api.create('api/user/test_slack_webhook', { webhook })
                            if (response.success) {
                                return webhook
                            } else {
                                actions.testWebhookFailure(response.error)
                            }
                        } catch (error: any) {
                            actions.testWebhookFailure(error.message)
                        }
                    }
                    return null
                },
            },
        ],
        removedWebhook: [
            null,
            {
                removeWebhook: () => {
                    teamLogic.actions.updateCurrentTeam({ slack_incoming_webhook: '' })
                    return null
                },
            },
        ],
    }),
    listeners: () => ({
        testWebhookSuccess: async ({ testedWebhook }) => {
            if (testedWebhook) {
                teamLogic.actions.updateCurrentTeam({ slack_incoming_webhook: testedWebhook })
            }
        },
        testWebhookFailure: ({ error }) => {
            lemonToast.error(capitalizeFirstLetter(error))
        },
    }),
    selectors: {
        loading: [
            (s) => [s.testedWebhookLoading, teamLogic.selectors.currentTeamLoading],
            (testedWebhookLoading: boolean, currentTeamLoading: boolean) => testedWebhookLoading || currentTeamLoading,
        ],
    },
})
