import { useActions, useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { InviteTeamMatesComponent } from 'scenes/settings/organization/InviteModal'

import { ProductKey, OnboardingStepKey } from '~/types'

import { onboardingLogic } from './onboardingLogic'
import { OnboardingStep } from './OnboardingStep'

export const OnboardingInviteTeammates = ({ stepKey }: { stepKey: OnboardingStepKey }): JSX.Element => {
    const { preflight } = useValues(preflightLogic)
    const { productKey } = useValues(onboardingLogic)
    const { inviteTeamMembers } = useActions(inviteLogic)
    const { invitesToSend, canSubmit: canSubmitInvites } = useValues(inviteLogic)

    const titlePrefix = (): string => {
        switch (productKey) {
            case ProductKey.PRODUCT_ANALYTICS:
                return 'Analytics are'
            case ProductKey.SESSION_REPLAY:
                return 'Replays are'
            case ProductKey.FEATURE_FLAGS:
                return 'Feature flags are'
            case ProductKey.SURVEYS:
                return 'Surveys are'
            case ProductKey.ERROR_TRACKING:
                return 'Tracking errors is'
            default:
                return 'PostHog is'
        }
    }

    const likeTo = (): string => {
        switch (productKey) {
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
            title="Invite teammates"
            stepKey={stepKey}
            onContinue={() =>
                preflight?.email_service_available &&
                invitesToSend[0]?.target_email &&
                canSubmitInvites &&
                inviteTeamMembers()
            }
        >
            <div className="mb-6 mt-6">
                <p>
                    {titlePrefix()} better with friends ... or maybe even just coworkers. Ya know the ones who like to{' '}
                    {likeTo()}?{' '}
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
