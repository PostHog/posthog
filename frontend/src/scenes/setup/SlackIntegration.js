import React, { useState } from 'react'
import { kea, useActions, useKea, useValues } from 'kea'

import { userLogic } from '../userLogic'

const logic = kea({
    reducers: () => ({
        isSaved: [
            false,
            {
                [userLogic.actions.userUpdateRequest]: (_, { updateKey }) => (updateKey === 'slack' ? false : state),
                [userLogic.actions.userUpdateSuccess]: (_, { updateKey }) => (updateKey === 'slack' ? true : state),
            },
        ],
    }),
})

export function SlackIntegration() {
    const { user } = useValues(userLogic)
    const { isSaved } = useValues(logic)
    const { userUpdateRequest } = useActions(userLogic)
    const { slack_incoming_webhook: slackIncomingWebhook } = user.team
    const [editedWebhook, setEditedWebhook] = useState(slackIncomingWebhook || '')

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
                    userUpdateRequest({ team: { slack_incoming_webhook: editedWebhook } }, 'slack')
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
                    Save
                </button>
                {isSaved && (
                    <span className="text-success" style={{ marginLeft: 10 }}>
                        Webhook updated!
                    </span>
                )}
            </form>
        </div>
    )
}
