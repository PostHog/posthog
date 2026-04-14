import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { OnboardingStepKey } from '~/types'

import { onboardingLogic } from '../../onboardingLogic'

interface NextButtonProps {
    installationComplete: boolean
    size?: 'small' | 'medium'
}

export const NextButton = ({ installationComplete, size = 'medium' }: NextButtonProps): JSX.Element => {
    const { hasNextStep } = useValues(onboardingLogic)
    const { completeOnboarding, goToNextStep } = useActions(onboardingLogic)
    const { reportOnboardingStepCompleted, reportOnboardingStepSkipped } = useActions(eventUsageLogic)

    const advance = !hasNextStep ? completeOnboarding : goToNextStep
    const skipInstallation = (): void => {
        reportOnboardingStepSkipped(OnboardingStepKey.INSTALL)
        advance()
    }

    const continueInstallation = (): void => {
        reportOnboardingStepCompleted(OnboardingStepKey.INSTALL)
        advance()
    }

    if (!installationComplete) {
        return (
            <LemonButton type="secondary" size={size} onClick={skipInstallation}>
                Skip installation
            </LemonButton>
        )
    }

    return (
        <LemonButton
            data-attr="sdk-continue"
            sideIcon={hasNextStep ? <IconArrowRight /> : null}
            type="primary"
            status="alt"
            onClick={continueInstallation}
        >
            Next
        </LemonButton>
    )
}
