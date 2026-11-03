import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { GuidedWizardStepper } from 'lib/components/GuidedWizard/GuidedWizardStepper'

import { OnboardingStepKey } from '~/types'

import { OnboardingFlowHost } from '../OnboardingFlowHost'
import { stepKeyToTitle } from '../onboardingFlowUtils'
import { onboardingLogic } from '../onboardingLogic'
import { OnboardingStepFooterStartContext } from '../OnboardingStepFooterStartContext'
import { ProjectTokenSnippet } from '../shared/ProjectTokenSnippet'

export function SimpleOnboarding(): JSX.Element {
    const { flow, currentFlowStep, hasNextStep, isSkippingOnboarding, isCompleting } = useValues(onboardingLogic)
    const { skipSimpleOnboarding } = useActions(onboardingLogic)

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 pb-4 border-b border-primary">
                {currentFlowStep ? (
                    <GuidedWizardStepper
                        steps={flow.map((step) => ({
                            step: step.id,
                            label: step.label ?? stepKeyToTitle(step.stepKey) ?? '',
                        }))}
                        currentStep={currentFlowStep.id}
                        className="flex-wrap -ml-2"
                        aria-label="Setup progress"
                    />
                ) : (
                    <div />
                )}
                <ProjectTokenSnippet />
            </div>
            <OnboardingStepFooterStartContext.Provider
                value={
                    <LemonButton
                        type="tertiary"
                        size="small"
                        onClick={skipSimpleOnboarding}
                        loading={isSkippingOnboarding || isCompleting}
                        data-attr="simple-onboarding-skip"
                    >
                        {currentFlowStep?.stepKey === OnboardingStepKey.INVITE_TEAMMATES && !hasNextStep
                            ? 'Skip invites and finish'
                            : 'Skip setup'}
                    </LemonButton>
                }
            >
                {/* A block wrapper: the step's `mx-auto` content would shrink to fit as a flex child. */}
                <div>
                    <OnboardingFlowHost />
                </div>
            </OnboardingStepFooterStartContext.Provider>
        </div>
    )
}
