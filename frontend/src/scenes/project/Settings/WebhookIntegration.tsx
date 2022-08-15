import React, { useEffect, useState } from 'react'
import { useActions, useValues } from 'kea'
import { Input, Button, Col, Row } from 'antd'
import { teamLogic } from 'scenes/teamLogic'
import { webhookIntegrationLogic } from './webhookIntegrationLogic'

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

            <Input
                value={webhook}
                addonBefore="Webhook URL"
                onChange={(e) => setWebhook(e.target.value)}
                style={{ maxWidth: '40rem', marginBottom: '1rem', display: 'block' }}
                type="url"
                placeholder={
                    currentTeam?.slack_incoming_webhook ? '' : 'integration disabled – enter URL, then Test & Save'
                }
                disabled={loading}
                onPressEnter={() => testWebhook(webhook)}
            />
            <Row>
                <Col>
                    <Button
                        type="primary"
                        disabled={!webhook}
                        onClick={(e) => {
                            e.preventDefault()
                            testWebhook(webhook)
                        }}
                        loading={loading}
                    >
                        Test & Save
                    </Button>
                </Col>
                <Col style={{ marginLeft: 10 }}>
                    <Button
                        type="default"
                        danger
                        onClick={(e) => {
                            e.preventDefault()
                            removeWebhook()
                            setWebhook('')
                        }}
                        disabled={!currentTeam?.slack_incoming_webhook}
                    >
                        Clear & Disable
                    </Button>
                </Col>
            </Row>
        </div>
    )
}
