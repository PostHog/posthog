import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { OnboardingStepKey } from '~/types'

import { onboardingLogic } from '../../onboardingLogic'

interface NextButtonProps {
    installationComplete: boolean
    size?: 'small' | 'medium'
    /** Overrides the legacy onboardingLogic advance for flows (e.g. self-driving) that manage their own step state. */
    onAdvance?: () => void
}

export const NextButton = ({ installationComplete, size = 'medium', onAdvance }: NextButtonProps): JSX.Element => {
    const { hasNextStep, currentStepProductKey } = useValues(onboardingLogic)
    const { completeOnboarding, goToNextStep } = useActions(onboardingLogic)
    const { reportOnboardingStepCompleted, reportOnboardingStepSkipped } = useActions(eventUsageLogic)

    const advance = onAdvance ?? (!hasNextStep ? completeOnboarding : goToNextStep)
    const skipInstallation = (): void => {
        reportOnboardingStepSkipped(OnboardingStepKey.INSTALL, currentStepProductKey ?? undefined)
        advance()
    }

    const continueInstallation = (): void => {
        reportOnboardingStepCompleted(OnboardingStepKey.INSTALL, currentStepProductKey ?? undefined)
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
