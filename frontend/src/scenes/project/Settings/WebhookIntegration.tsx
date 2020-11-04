import React from 'react'
import { kea, useActions, useValues } from 'kea'
import api from 'lib/api'
import { Input, Button } from 'antd'
import { userLogic } from 'scenes/userLogic'
import { logicType } from 'types/scenes/project/Settings/WebhookIntegrationType'
import { UserType } from '~/types'
import { teamLogic } from 'scenes/teamLogic'

const WEBHOOK_SERVICES: Record<string, string> = {
    Slack: "slack.com",
    Discord: "discord.com",
    Teams: "office.com"
}

function resolveWebhookService(webhookUrl: string): string {
    for (const [service, domain] of Object.entries(WEBHOOK_SERVICES)) {
        if (webhookUrl.includes(domain)) return service
    }
    return 'your webhook service'
}

function adjustDiscordWebhook(webhookUrl: string): string {
    // We need Discord webhook URLs to end with /slack for proper handling, this ensures that
    return webhookUrl.replace(/\/*(?:posthog|slack)?$/, '/slack')
}

const logic = kea<logicType<UserType>>({
    actions: () => ({
        setEditedWebhook: (webhook: string) => ({ webhook }),
        saveWebhook: (webhook: string) => ({ webhook }),
        testAndSaveWebhook: true,
        setError: (error: string) => ({ error }),
    }),

    defaults: () => (state: Record<string, any>) => ({
        editedWebhook: userLogic.selectors.user(state, {})?.team?.slack_incoming_webhook,
    }),

    reducers: () => ({
        editedWebhook: [
            '',
            {
                setEditedWebhook: (_, { webhook }) => webhook,
                saveWebhook: (_, { webhook }) => webhook,
            },
        ],
        isSaving: [
            false,
            {
                saveWebhook: () => true,
                testAndSaveWebhook: () => true,
                setError: () => false,
                [teamLogic.actionTypes.updateCurrentTeamSuccess]: () => false,
                [teamLogic.actionTypes.updateCurrentTeamFailure]: () => false
            },
        ],
        isSaved: [
            false,
            {
                saveWebhook: () => false,
                testAndSaveWebhook: () => false,
                [teamLogic.actionTypes.updateCurrentTeamSuccess]: () => true,
                setEditedWebhook: () => false,
            },
        ],
        error: [
            null as string | null,
            {
                saveWebhook: () => null,
                testAndSaveWebhook: () => null,
                setError: (_, { error }) => error,
                setEditedWebhook: () => null,
            },
        ],
    }),

    listeners: ({ actions, values }) => ({
        testAndSaveWebhook: async () => {
            let { editedWebhook } = values
            if (editedWebhook) {
                if (editedWebhook.includes('discord.com')) editedWebhook = adjustDiscordWebhook(editedWebhook)
                actions.setEditedWebhook(editedWebhook)
                try {
                    await api.create('api/user/@me/test_slack_webhook', { webhook: editedWebhook })
                    actions.saveWebhook(editedWebhook)
                } catch (error) {
                    actions.setError(error.detail)
                }
            } else {
                actions.saveWebhook(editedWebhook)
            }
        },
        saveWebhook: async () => {
            await teamLogic.actions.updateCurrentTeam({ slack_incoming_webhook: values.editedWebhook }, 'webhook')
        },
    }),
})

export function WebhookIntegration(): JSX.Element {
    const { isSaved, isSaving, error, editedWebhook } = useValues(logic)
    const { testAndSaveWebhook, setEditedWebhook } = useActions(logic)

    return (
        <div>
            <p>
                Send notifications when selected Actions are performed by users.<br/>
                Guidance on integrating with webhooks available in our docs,{' '}
                <a href="https://posthog.com/docs/integrations/slack">for Slack</a> and{' '}
                <a href="https://posthog.com/docs/integrations/microsoft-teams">for Microsoft Teams</a>. Discord is also supported.
            </p>
            <Input
                value={editedWebhook}
                addonBefore="Webhook URL"
                onChange={(e) => setEditedWebhook(e.target.value)}
                style={{ maxWidth: '40rem', marginBottom: '1rem', display: 'block' }}
                type="url"
                placeholder="integration disabled – enter URL to enable"
            />
            <Button
                type="primary"
                onClick={(e) => {
                    e.preventDefault()
                    testAndSaveWebhook()
                }}
            >
                {isSaving ? '...' : editedWebhook ? 'Test & Save' : 'Save'}
            </Button>

            {error && (
                <span className="text-danger" style={{ marginLeft: 10 }}>
                    Error: {error}
                </span>
            )}

            {isSaved && (
                <span className="text-success" style={{ marginLeft: 10 }}>
                    Success:{' '}
                    {editedWebhook
                        ? `You should see a message on ${resolveWebhookService(editedWebhook)}.`
                        : 'Disabled integration.'}
                </span>
            )}
        </div>
    )
}
