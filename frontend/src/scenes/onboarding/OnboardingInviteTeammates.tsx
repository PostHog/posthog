import { useActions, useValues } from 'kea'
import { PhonePairHogs } from 'lib/components/hedgehogs'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { InviteTeamMatesComponent } from 'scenes/settings/organization/InviteModal'

import { ProductKey } from '~/types'

import { onboardingLogic, OnboardingStepKey } from './onboardingLogic'
import { OnboardingStep } from './OnboardingStep'

export const OnboardingInviteTeammates = ({ stepKey }: { stepKey: OnboardingStepKey }): JSX.Element => {
    const { preflight } = useValues(preflightLogic)
    const { product } = useValues(onboardingLogic)
    const { inviteTeamMembers } = useActions(inviteLogic)

    const titlePrefix = (): string => {
        switch (product?.type) {
            case ProductKey.PRODUCT_ANALYTICS:
                return 'Analytics are'
            case ProductKey.SESSION_REPLAY:
                return 'Replays are'
            case ProductKey.FEATURE_FLAGS:
                return 'Feature flags are'
            case ProductKey.SURVEYS:
                return 'Surveys are'
            default:
                return 'PostHog is'
        }
    }

    const likeTo = (): string => {
        switch (product?.type) {
            case ProductKey.PRODUCT_ANALYTICS:
                return 'dig into the data'
            case ProductKey.SESSION_REPLAY:
                return 'see how people use your product'
            case ProductKey.FEATURE_FLAGS:
                return 'customize user experiences'
            case ProductKey.SURVEYS:
                return 'ask all the questions'
            default:
                return 'dig into the data'
        }
    }

    return (
        <OnboardingStep
            title={`${titlePrefix()} better with friends.`}
            stepKey={stepKey}
            hedgehog={<PhonePairHogs height={120} width={288} />}
            continueAction={() => preflight?.email_service_available && inviteTeamMembers()}
        >
            <div className="mb-6">
                <p>
                    ...or maybe even just coworkers. Ya know the ones who like to {likeTo()}?{' '}
                    {preflight?.email_service_available && (
                        <span>
                            Enter their email below and we'll send them a custom invite link. Invites expire after 3
                            days.
                        </span>
                    )}
                </p>
                {!preflight?.email_service_available && (
                    <p>
                        This PostHog instance isn't configured to send emails. In the meantime, enter your teammates'
                        emails below to generate their custom invite links.{' '}
                        <strong>You'll need to share the links with your project members manually</strong>. You can
                        invite more people later.
                    </p>
                )}
            </div>
            <InviteTeamMatesComponent />
        </OnboardingStep>
    )
}
