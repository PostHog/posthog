import React from 'react'
import { kea, useActions, useValues } from 'kea'
import api from 'lib/api'
import { Input, Button } from 'antd'
import { userLogic } from 'scenes/userLogic'
import { logicType } from './WebhookIntegrationType'
import { UserType } from '~/types'
import { toast } from 'react-toastify'
import { capitalizeFirstLetter } from 'lib/utils'

const WEBHOOK_SERVICES: Record<string, string> = {
    Slack: 'slack.com',
    Discord: 'discord.com',
    Teams: 'office.com',
}

function resolveWebhookService(webhookUrl: string): string {
    for (const [service, domain] of Object.entries(WEBHOOK_SERVICES)) {
        if (webhookUrl.includes(domain + '/')) {
            return service
        }
    }
    return 'your webhook service'
}

function adjustDiscordWebhook(webhookUrl: string): string {
    // We need Discord webhook URLs to end with /slack for proper handling, this ensures that
    return webhookUrl.replace(/\/*(?:posthog|slack)?\/?$/, '/slack')
}

const logic = kea<logicType<UserType>>({
    actions: () => ({
        setEditedWebhook: (webhook: string) => ({ webhook }),
        saveWebhook: (webhook: string) => ({ webhook }),
        testThenSaveWebhook: true,
        handleTestError: (error: string) => ({ error }),
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
                testThenSaveWebhook: () => true,
                handleTestError: () => false,
                [userLogic.actionTypes.userUpdateSuccess]: (state, { updateKey }) =>
                    updateKey === 'webhook' ? false : state,
                [userLogic.actionTypes.userUpdateFailure]: (state, { updateKey }) =>
                    updateKey === 'webhook' ? false : state,
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
            userLogic.actions.userUpdateRequest({ team: { slack_incoming_webhook: values.editedWebhook } }, 'webhook')
        },
        handleTestError: ({ error }) => {
            toast.error(
                <div>
                    <h1>
                        {capitalizeFirstLetter(resolveWebhookService(values.editedWebhook))} webhook validation returned
                        error:
                    </h1>
                    <p>{error}</p>
                </div>
            )
        },
        [userLogic.actionTypes.userUpdateSuccess]: ({ updateKey }) => {
            if (updateKey === 'webhook') {
                toast.success(
                    values.editedWebhook
                        ? `Webhook integration enabled. You should see a message on ${resolveWebhookService(
                              values.editedWebhook
                          )}.`
                        : 'Webhook integration disabled.'
                )
            }
        },
    }),
})

export function WebhookIntegration(): JSX.Element {
    const { isSaving, editedWebhook } = useValues(logic)
    const { testThenSaveWebhook, setEditedWebhook } = useActions(logic)

    return (
        <div>
            <p>
                Send notifications when selected Actions are performed by users.
                <br />
                Guidance on integrating with webhooks available in our docs,{' '}
                <a href="https://posthog.com/docs/integrations/slack">for Slack</a> and{' '}
                <a href="https://posthog.com/docs/integrations/microsoft-teams">for Microsoft Teams</a>. Discord is also
                supported.
            </p>
            <Input
                value={editedWebhook}
                addonBefore="Webhook URL"
                onChange={(e) => setEditedWebhook(e.target.value)}
                style={{ maxWidth: '40rem', marginBottom: '1rem', display: 'block' }}
                type="url"
                placeholder={'integration disabled – type a URL to enable'}
            />
            <Button
                type="primary"
                onClick={(e) => {
                    e.preventDefault()
                    testThenSaveWebhook()
                }}
            >
                {isSaving ? '...' : editedWebhook ? 'Test & Save' : 'Save'}
            </Button>
        </div>
    )
}
