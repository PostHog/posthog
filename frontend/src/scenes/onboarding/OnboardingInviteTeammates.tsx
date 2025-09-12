import { useActions, useValues } from 'kea'

import { LemonDivider } from '@posthog/lemon-ui'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { EmailUnavailableForInvitesBanner, InviteTeamMatesComponent } from 'scenes/settings/organization/InviteModal'
import { InvitesTable } from 'scenes/settings/organization/Invites'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'

import { OnboardingStepKey, ProductKey } from '~/types'

import { OnboardingStep } from './OnboardingStep'
import { onboardingLogic } from './onboardingLogic'

export const OnboardingInviteTeammates = ({ stepKey }: { stepKey: OnboardingStepKey }): JSX.Element => {
    const { preflight } = useValues(preflightLogic)
    const { productKey } = useValues(onboardingLogic)
    const { inviteTeamMembers } = useActions(inviteLogic)
    const { invitesToSend, canSubmit: canSubmitInvites } = useValues(inviteLogic)
    const { invites } = useValues(inviteLogic)

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

    const showInviteLinks = !preflight?.email_service_available && invites.length > 0

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
            </div>
            <InviteTeamMatesComponent />
            {showInviteLinks && (
                <>
                    <LemonDivider className="my-4" />
                    <EmailUnavailableForInvitesBanner />
                    <div className="mt-4">
                        <h3>Invite Links</h3>
                        <InvitesTable />
                    </div>
                </>
            )}
        </OnboardingStep>
    )
}
