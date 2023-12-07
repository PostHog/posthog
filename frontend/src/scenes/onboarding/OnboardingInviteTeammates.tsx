import { useValues } from 'kea'
import { PhonePairHogs } from 'lib/components/hedgehogs'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { InviteTeamMatesComponent } from 'scenes/settings/organization/InviteModal'
import { teamLogic } from 'scenes/teamLogic'

import { OnboardingStepKey } from './onboardingLogic'
import { OnboardingStep } from './OnboardingStep'

export const OnboardingInviteTeammates = ({ stepKey }: { stepKey: OnboardingStepKey }): JSX.Element => {
    const { preflight } = useValues(preflightLogic)

    const { currentTeam } = useValues(teamLogic)
    const completed_onboarding_products = Object.keys(currentTeam?.has_completed_onboarding_for || {})
    const productAnalyticsOnboarded = completed_onboarding_products.includes('product_analytics')
    const surveysOnboarded = completed_onboarding_products.includes('surveys')
    const sessionReplayOnboarded = completed_onboarding_products.includes('session_replay')

    return (
        <OnboardingStep title={`PostHog is better with teammates`} stepKey={stepKey}>
            <div className="flex items-center py-8 gap-8 mx-16">
                <span>
                    Invite your teammates so you can {productAnalyticsOnboarded && 'share your dashboard insights'}
                    {surveysOnboarded &&
                        `${productAnalyticsOnboarded ? ' and ' : ''}review your survey results together`}
                    {sessionReplayOnboarded &&
                        `${
                            surveysOnboarded || productAnalyticsOnboarded ? 'and' : ''
                        } have a session replay watch party`}
                    {!(productAnalyticsOnboarded || surveysOnboarded || sessionReplayOnboarded) &&
                        'supercharge your analytics experience'}
                    !
                </span>
                <PhonePairHogs height={120} width={288} />
            </div>
            {preflight?.email_service_available ? (
                <p>Enter their email below and we'll send them a custom invite link. Invites expire after 3 days.</p>
            ) : (
                <p>
                    This PostHog instance isn't configured to send emails. In the meantime, enter your teammates' emails
                    below to generate their custom invite links.{' '}
                    <strong>You'll need to share the links with your project members manually</strong>. You can invite
                    more people later.
                </p>
            )}
            <InviteTeamMatesComponent />
        </OnboardingStep>
    )
}
