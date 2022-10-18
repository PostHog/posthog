import { useEffect, useState } from 'react'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { webhookIntegrationLogic } from './webhookIntegrationLogic'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

export function WebhookIntegration(): JSX.Element {
    const [webhook, setWebhook] = useState('')
    const { testWebhook, removeWebhook } = useActions(webhookIntegrationLogic)
    const { loading } = useValues(webhookIntegrationLogic)
    const { currentTeam } = useValues(teamLogic)

    useEffect(() => {
        if (currentTeam?.slack_incoming_webhook) {
            setWebhook(currentTeam?.slack_incoming_webhook)
        }
    }, [currentTeam])

    return (
        <div>
            <p>
                Send notifications when selected actions are performed by users.
                <br />
                Guidance on integrating with webhooks available in our docs,{' '}
                <a href="https://posthog.com/docs/integrate/third-party/slack">for Slack</a> and{' '}
                <a href="https://posthog.com/docs/integrations/microsoft-teams">for Microsoft Teams</a>. Discord is also
                supported.
            </p>

            <div className="space-y-4" style={{ maxWidth: '40rem' }}>
                <LemonInput
                    value={webhook}
                    onChange={setWebhook}
                    type="url"
                    placeholder={
                        currentTeam?.slack_incoming_webhook ? '' : 'integration disabled - enter URL, then Test & Save'
                    }
                    disabled={loading}
                    onPressEnter={() => testWebhook(webhook)}
                />
                <div className="flex items-center gap-2">
                    <LemonButton
                        type="primary"
                        disabled={!webhook}
                        onClick={(e) => {
                            e.preventDefault()
                            testWebhook(webhook)
                        }}
                        loading={loading}
                    >
                        Test & Save
                    </LemonButton>
                    <LemonButton
                        status="danger"
                        type="secondary"
                        onClick={(e) => {
                            e.preventDefault()
                            removeWebhook()
                            setWebhook('')
                        }}
                        disabled={!currentTeam?.slack_incoming_webhook}
                    >
                        Clear & Disable
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
