import React from 'react'
import { kea, useActions, useValues } from 'kea'
import api from 'lib/api'
import { Input, Button } from 'antd'
import { userLogic } from 'scenes/userLogic'
import { logicType } from 'types/scenes/project/Settings/WebhookIntegrationType'
import { UserType } from '~/types'

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
                [userLogic.actionTypes.userUpdateSuccess]: (state, { updateKey }) =>
                    updateKey === 'slack' ? false : state,
                [userLogic.actionTypes.userUpdateFailure]: (state, { updateKey }) =>
                    updateKey === 'slack' ? false : state,
            },
        ],
        isSaved: [
            false,
            {
                saveWebhook: () => false,
                testAndSaveWebhook: () => false,
                [userLogic.actionTypes.userUpdateSuccess]: (state, { updateKey }) =>
                    updateKey === 'slack' ? true : state,
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
            const { editedWebhook } = values
            if (editedWebhook) {
                try {
                    const response = await api.create('api/user/test_slack_webhook', { webhook: editedWebhook })

                    if (response.success) {
                        actions.saveWebhook(editedWebhook)
                    } else {
                        actions.setError(response.error)
                    }
                } catch (error) {
                    actions.setError(error.message)
                }
            } else {
                actions.saveWebhook(editedWebhook)
            }
        },
        saveWebhook: async () => {
            userLogic.actions.userUpdateRequest({ team: { slack_incoming_webhook: values.editedWebhook } }, 'slack')
        },
    }),
})

export function WebhookIntegration({ user }: { user: UserType }): JSX.Element {
    const { isSaved, isSaving, error, editedWebhook } = useValues(logic)
    const { testAndSaveWebhook, setEditedWebhook } = useActions(logic)

    return (
        <div>
            <p>
                Guidance on integrating with webhooks available in our docs,{' '}
                <a href="https://posthog.com/docs/integrations/slack">for Slack</a> and{' '}
                <a href="https://posthog.com/docs/integrations/microsoft-teams">for Microsoft Teams</a>.
            </p>
            <Input
                value={editedWebhook}
                addonBefore="Webhook URL"
                onChange={(e) => setEditedWebhook(e.target.value)}
                style={{ maxWidth: '40rem', marginBottom: '1rem', display: 'block' }}
                type="url"
                placeholder={
                    user.is_multi_tenancy ? 'temporarily unavailable on PostHog Cloud' : 'integration disabled'
                }
                disabled={user.is_multi_tenancy}
            />
            <Button
                type="primary"
                onClick={(e) => {
                    e.preventDefault()
                    testAndSaveWebhook()
                }}
                disabled={user.is_multi_tenancy}
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
                        ? `you should see a message on ${editedWebhook.includes('slack.com') ? 'Slack' : 'Teams'}`
                        : 'integration disabled'}
                </span>
            )}
        </div>
    )
}
