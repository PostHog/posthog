import React, { useEffect, useState } from 'react'
import { useActions, useValues } from 'kea'
import { Input, Button } from 'antd'
import { teamLogic } from 'scenes/teamLogic'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { webhookIntegrationLogic } from './webhookIntegrationLogic'

export function AsyncActionMappingNotice(): JSX.Element {
    return (
        <p>
            Please note that webhooks and actions may be delayed up to 5 minutes due to open-source PostHog
            configuration.
        </p>
    )
}

export function WebhookIntegration(): JSX.Element {
    const [webhook, setWebhook] = useState('')
    const { testWebhook } = useActions(webhookIntegrationLogic)
    const { loading } = useValues(webhookIntegrationLogic)
    const { preflight } = useValues(preflightLogic)
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
                <a href="https://posthog.com/docs/integrations/slack">for Slack</a> and{' '}
                <a href="https://posthog.com/docs/integrations/microsoft-teams">for Microsoft Teams</a>. Discord is also
                supported.
            </p>
            {preflight?.is_async_event_action_mapping_enabled && <AsyncActionMappingNotice />}

            <Input
                value={webhook}
                addonBefore="Webhook URL"
                onChange={(e) => setWebhook(e.target.value)}
                style={{ maxWidth: '40rem', marginBottom: '1rem', display: 'block' }}
                type="url"
                placeholder={'integration disabled – type a URL to enable'}
                disabled={loading}
                onPressEnter={() => testWebhook(webhook)}
            />
            <Button
                type="primary"
                onClick={(e) => {
                    e.preventDefault()
                    testWebhook(webhook)
                }}
                loading={loading}
            >
                {webhook ? 'Test & Save' : 'Save'}
            </Button>
        </div>
    )
}
