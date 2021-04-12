import React from 'react'
import { kea, useActions, useValues } from 'kea'
import api from 'lib/api'
import { Input, Button } from 'antd'
import { logicType } from './WebhookIntegrationType'
import { errorToast } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { preflightLogic } from 'scenes/PreflightCheck/logic'

function adjustDiscordWebhook(webhookUrl: string): string {
    // We need Discord webhook URLs to end with /slack for proper handling, this ensures that
    return webhookUrl.replace(/\/*(?:posthog|slack)?\/?$/, '/slack')
}

const logic = kea<logicType>({
    actions: () => ({
        setEditedWebhook: (webhook: string) => ({ webhook }),
        saveWebhook: (webhook: string) => ({ webhook }),
        testThenSaveWebhook: true,
        handleTestError: (error: string) => ({ error }),
    }),
    defaults: () => (state: Record<string, any>) => ({
        editedWebhook: teamLogic.selectors.currentTeam(state, {})?.slack_incoming_webhook,
    }),
    reducers: () => ({
        editedWebhook: [
            '',
            {
                setEditedWebhook: (_, { webhook }) => webhook,
                saveWebhook: (_, { webhook }) => webhook,
            },
        ],
    }),
    listeners: ({ actions, values }) => ({
        testThenSaveWebhook: async () => {
            let { editedWebhook } = values

            if (editedWebhook?.includes('discord.com/')) {
                editedWebhook = adjustDiscordWebhook(editedWebhook)
                actions.setEditedWebhook(editedWebhook)
            }

            if (editedWebhook) {
                try {
                    const response = await api.create('api/user/test_slack_webhook', { webhook: editedWebhook })
                    if (response.success) {
                        actions.saveWebhook(editedWebhook)
                    } else {
                        actions.handleTestError(response.error)
                    }
                } catch (error) {
                    actions.handleTestError(error.message)
                }
            } else {
                actions.saveWebhook(editedWebhook)
            }
        },
        saveWebhook: async () => {
            teamLogic.actions.updateCurrentTeam({ slack_incoming_webhook: values.editedWebhook })
        },
        handleTestError: ({ error }) => {
            errorToast('Error validating your webhook', 'Your webhook returned the following error response:', error)
        },
        [teamLogic.actionTypes.loadCurrentTeamSuccess]: () => {
            const webhook = teamLogic.values.currentTeam?.slack_incoming_webhook
            if (webhook) {
                actions.setEditedWebhook(webhook)
            }
        },
    }),
})

export function AsyncActionMappingNotice(): JSX.Element {
    return (
        <p>
            Please note that webhooks and actions may be delayed up to 5 minutes due to open-source PostHog
            configuration.
        </p>
    )
}

export function WebhookIntegration(): JSX.Element {
    const { editedWebhook } = useValues(logic)
    const { testThenSaveWebhook, setEditedWebhook } = useActions(logic)
    const { preflight } = useValues(preflightLogic)
    const { currentTeamLoading } = useValues(teamLogic)

    return (
        <div>
            <p>
                Send notifications when selected actions are performed by users.
                <br />
                Guidance on integrating with webhooks available in our docs,{' '}
                <a href="https://posthog.com/docs/integrations/slack">for Slack</a> and{' '}
                <a href="https://posthog.com/docs/integrations/microsoft-teams">for Microsoft Teams</a>. Discord is also
                supported.
            </p>
            {preflight?.is_async_event_action_mapping_enabled && <AsyncActionMappingNotice />}

            <Input
                value={editedWebhook}
                addonBefore="Webhook URL"
                onChange={(e) => setEditedWebhook(e.target.value)}
                style={{ maxWidth: '40rem', marginBottom: '1rem', display: 'block' }}
                type="url"
                placeholder={'integration disabled – type a URL to enable'}
                disabled={currentTeamLoading}
            />
            <Button
                type="primary"
                onClick={(e) => {
                    e.preventDefault()
                    testThenSaveWebhook()
                }}
                loading={currentTeamLoading}
            >
                {editedWebhook ? 'Test & Save' : 'Save'}
            </Button>
        </div>
    )
}
