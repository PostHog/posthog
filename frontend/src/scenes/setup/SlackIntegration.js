import React from 'react'
import { kea, useActions, useValues } from 'kea'
import { userLogic } from '../userLogic'
import api from 'lib/api'

const logic = kea({
    actions: () => ({
        setEditedWebhook: webhook => ({ webhook }),
        saveWebhook: true,
        testAndSaveWebhook: true,
        setError: error => ({ error }),
    }),

    reducers: ({ actions }) => ({
        editedWebhook: [
            state => userLogic.selectors.user(state)?.team?.slack_incoming_webhook,
            {
                [actions.setEditedWebhook]: (_, { webhook }) => webhook,
            },
        ],
        isSaving: [
            false,
            {
                [actions.saveWebhook]: () => true,
                [actions.testAndSaveWebhook]: () => true,
                [actions.setError]: () => false,
                [userLogic.actions.userUpdateSuccess]: (_, { updateKey }) => (updateKey === 'slack' ? false : state),
                [userLogic.actions.userUpdateFailure]: (_, { updateKey }) => (updateKey === 'slack' ? false : state),
            },
        ],
        isSaved: [
            false,
            {
                [actions.saveWebhook]: () => false,
                [actions.testAndSaveWebhook]: () => false,
                [userLogic.actions.userUpdateSuccess]: (_, { updateKey }) => (updateKey === 'slack' ? true : state),
                [actions.setEditedWebhook]: () => false,
            },
        ],
        error: [
            null,
            {
                [actions.saveWebhook]: () => null,
                [actions.testAndSaveWebhook]: () => null,
                [actions.setError]: (_, { error }) => error,
                [actions.setEditedWebhook]: () => null,
            },
        ],
    }),

    listeners: ({ actions, values }) => ({
        [actions.testAndSaveWebhook]: async () => {
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
        [actions.saveWebhook]: async () => {
            userLogic.actions.userUpdateRequest({ team: { slack_incoming_webhook: values.editedWebhook } }, 'slack')
        },
    }),
})

export function SlackIntegration() {
    const { isSaved, isSaving, error, editedWebhook } = useValues(logic)
    const { testAndSaveWebhook, setEditedWebhook } = useActions(logic)

    return (
        <div>
            <label>
                Enter your Slack webhook URL here.{' '}
                <a href="https://docs.posthog.com/#/integrations/slack">
                    Read the docs to find out how to get this value.
                </a>
            </label>
            <form
                onSubmit={e => {
                    e.preventDefault()
                    testAndSaveWebhook()
                }}
            >
                <div style={{ marginBottom: 5 }}>
                    <input
                        value={editedWebhook}
                        onChange={e => setEditedWebhook(e.target.value)}
                        style={{ display: 'inline-block', maxWidth: 700 }}
                        type="url"
                        className="form-control"
                    />
                </div>

                <button className="btn btn-success" type="submit">
                    {isSaving ? '...' : editedWebhook ? 'Test & Save' : 'Save'}
                </button>

                {error && (
                    <span className="text-danger" style={{ marginLeft: 10 }}>
                        Error: {error}
                    </span>
                )}

                {isSaved && (
                    <span className="text-success" style={{ marginLeft: 10 }}>
                        {editedWebhook ? 'All good! You should see a message on Slack!' : 'Slack integration removed!'}
                    </span>
                )}
            </form>
        </div>
    )
}
