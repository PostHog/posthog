import { LemonBanner, LemonButton, LemonInput, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useEffect, useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { webhookIntegrationLogic } from './webhookIntegrationLogic'

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

    if (featureFlags[FEATURE_FLAGS.WEBHOOKS_DENYLIST]) {
        return (
            <div>
                <p>
                    Webhooks are currently not available for your organization.{' '}
                    <Link onClick={() => openSupportForm({ kind: 'support', target_area: 'apps' })}>
                        Contact support
                    </Link>
                </p>
            </div>
        )
    }

    const deprecationNotice = (
        <LemonBanner
            type="warning"
            action={{
                children: 'Go to Actions',
                to: urls.actions(),
            }}
        >
            Webhooks have upgraded and can now be configured per action, allowing multiple webhook destinations.
        </LemonBanner>
    )

    // Show nothing if they didn't have a webhook enabled
    if (featureFlags[FEATURE_FLAGS.MULTIPLE_ACTION_WEBHOOKS] && !currentTeam?.slack_incoming_webhook) {
        return <div>{deprecationNotice}</div>
    }

    return (
        <div className="space-y-2">
            <FlaggedFeature flag="multiple-action-webhooks">{deprecationNotice}</FlaggedFeature>
            <p>
                Send notifications when selected actions are performed by users.
                <br />
                Guidance on integrating with webhooks available in our docs,{' '}
                <Link to="https://posthog.com/docs/integrate/third-party/slack">for Slack</Link> and{' '}
                <Link to="https://posthog.com/docs/webhooks/microsoft-teams">for Microsoft Teams</Link>. Discord is also
                supported.
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
