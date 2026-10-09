import { LemonBanner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { PersonalCodexIntegration } from 'scenes/settings/user/PersonalCodexIntegration'

import { ClaudeSubscriptionConnection } from './ClaudeSubscriptionConnection'
import { SettingsSection } from './SettingsSection'

function Subscription({
    name,
    description,
    children,
}: {
    name: string
    description: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex max-w-180 flex-col gap-2">
            <div>
                <h3 className="m-0 text-base font-semibold">{name}</h3>
                <p className="m-0 text-secondary text-xs">{description}</p>
            </div>
            {children}
        </div>
    )
}

/** The subscriptions of the signed-in user that a run can use in place of PostHog AI credits. */
export function SubscriptionsSection(): JSX.Element {
    const codexEnabled = useFeatureFlag('POSTHOG_CODE_CODEX_OWN_SUBSCRIPTION_CLOUD')
    const claudeEnabled = useFeatureFlag('CLOUD_AGENTS_CLAUDE_SUBSCRIPTION_STORAGE')

    return (
        <SettingsSection
            title="Bring your own subscription"
            description="A subscription is yours, and no one else in the project can use it. With the automatic option, a run uses your subscription for its agent when one is connected, and PostHog AI credits when none is. A run that asks for your subscription by name fails if it is not connected."
            data-attr="cloud-agents-subscriptions"
        >
            {codexEnabled || claudeEnabled ? (
                <LemonBanner type="warning" className="max-w-180">
                    The agent runs code in the sandbox, and that code may be able to read the sign-in that the run uses.
                    Run agents only on repositories that you trust.
                </LemonBanner>
            ) : (
                <LemonBanner type="info" className="max-w-180">
                    Subscriptions are not available for your organization yet. Runs use PostHog AI credits.
                </LemonBanner>
            )}
            {codexEnabled && (
                <Subscription
                    name="Codex"
                    description="Connect your ChatGPT account so your Codex runs use your own ChatGPT plan. The connection is yours and applies in every project."
                >
                    <PersonalCodexIntegration />
                </Subscription>
            )}
            {claudeEnabled && (
                <Subscription
                    name="Claude"
                    description="Connect your Claude subscription so your Claude runs use your own Claude plan. The connection is yours and applies in every project."
                >
                    <ClaudeSubscriptionConnection />
                </Subscription>
            )}
        </SettingsSection>
    )
}
