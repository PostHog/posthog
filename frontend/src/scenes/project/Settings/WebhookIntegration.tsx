import { useEffect, useState } from 'react'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { webhookIntegrationLogic } from './webhookIntegrationLogic'
import { LemonButton, LemonInput, Link } from '@posthog/lemon-ui'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { supportLogic } from 'lib/components/Support/supportLogic'

export function WebhookIntegration(): JSX.Element {
    const [webhook, setWebhook] = useState('')
    const { testWebhook, removeWebhook } = useActions(webhookIntegrationLogic)
    const { loading } = useValues(webhookIntegrationLogic)
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { openSupportForm } = useActions(supportLogic)

    useEffect(() => {
        if (currentTeam?.slack_incoming_webhook) {
            setWebhook(currentTeam?.slack_incoming_webhook)
        }
    }, [currentTeam])

    const webhooks_blacklisted = featureFlags[FEATURE_FLAGS.WEBHOOKS_DENYLIST]
    if (webhooks_blacklisted) {
        return (
            <div>
                <p>
                    Webhooks are currently not available for your organization.{' '}
                    <Link onClick={() => openSupportForm('support', 'apps')}>Contact support</Link>
                </p>
            </div>
        )
    }

    return (
        <div>
            <p>
                Send notifications when selected actions are performed by users.
                <br />
                Guidance on integrating with webhooks available in our docs,{' '}
                <Link to="https://posthog.com/docs/integrate/third-party/slack">for Slack</Link> and{' '}
                <Link to="https://posthog.com/docs/integrations/microsoft-teams">for Microsoft Teams</Link>. Discord is
                also supported.
            </p>

            <div className="space-y-4 max-w-160">
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
