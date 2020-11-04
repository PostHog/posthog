import React from 'react'
import { kea, useActions, useValues } from 'kea'
import { Input, Button } from 'antd'
import { userLogic } from 'scenes/userLogic'
import { logicType } from 'types/scenes/project/Settings/WebhookIntegrationType'
import { UserType } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { toast } from 'react-toastify'

const WEBHOOK_SERVICES: Record<string, string> = {
    Slack: "slack.com",
    Discord: "discord.com",
    Teams: "office.com"
}

function resolveWebhookService(webhookUrl: string | null): string | null {
    if (!webhookUrl) return null
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
        saveWebhook: true,
        saveWebhookSuccess: true,
        testAndSaveWebhook: true,
        setError: (error: string) => ({ error }),
    }),

    defaults: () => (state: Record<string, any>) => ({
        editedWebhook: userLogic.selectors.user(state, {})?.team?.incoming_webhook,
    }),

    reducers: () => ({
        editedWebhook: [
            '',
            {
                setEditedWebhook: (_, { webhook }) => webhook,
            },
        ],
        isSaving: [
            false,
            {
                saveWebhook: () => true,
                setError: () => false,
                [teamLogic.actionTypes.updateCurrentTeamSuccess]: () => false,
                [teamLogic.actionTypes.updateCurrentTeamFailure]: () => false
            },
        ],
        isSaved: [
            false,
            {
                saveWebhook: () => false,
                [teamLogic.actionTypes.updateCurrentTeamSuccess]: () => true,
                setEditedWebhook: () => false,
            },
        ],
    }),

    listeners: ({ actions, values }) => ({
        saveWebhook: async () => {
            let { editedWebhook } = values
            if (editedWebhook?.includes('discord.com')) {
                editedWebhook = adjustDiscordWebhook(editedWebhook)
                actions.setEditedWebhook(editedWebhook)
            }
            await teamLogic.actions.updateCurrentTeam({ incoming_webhook: editedWebhook })
            actions.saveWebhookSuccess()
        },
        saveWebhookSuccess: () => {
            const service = resolveWebhookService(values.editedWebhook)
            toast.success(service
                ? `Webhook enabled. You should see a message on ${service}.`
                : 'Disabled webhook integration.')
        },
    }),
})

export function WebhookIntegration(): JSX.Element {
    const { isSaved, isSaving, editedWebhook } = useValues(logic)
    const { saveWebhook, setEditedWebhook } = useActions(logic)

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
                    saveWebhook()
                }}
            >
                {isSaving ? '...' : editedWebhook ? 'Test & Save' : 'Save'}
            </Button>
        </div>
    )
}
