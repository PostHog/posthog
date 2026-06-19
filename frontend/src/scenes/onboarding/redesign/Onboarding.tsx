import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Logo } from 'lib/brand/Logo'

import { onboardingLogic, type OnboardingStepKey } from './onboardingLogic'
import { OnboardingPreview } from './preview/OnboardingPreview'
import { CompanyStep } from './steps/CompanyStep'
import { CreateOrgStep } from './steps/CreateOrgStep'

// Titles for steps whose bodies are not built yet. Each step PR replaces its placeholder with the real component.
const PLACEHOLDER_TITLES: Partial<Record<OnboardingStepKey, string>> = {
    install: 'Install PostHog',
    configure: 'Configure',
    learn: 'Learn PostHog',
    done: "You're set",
}

function StepBody({ stepKey }: { stepKey: OnboardingStepKey }): JSX.Element {
    switch (stepKey) {
        case 'create_org':
            return <CreateOrgStep />
        case 'company':
            return <CompanyStep />
        default:
            return (
                <div className="max-w-xl">
                    <h1 className="text-3xl font-bold text-default">{PLACEHOLDER_TITLES[stepKey]}</h1>
                    <p className="text-secondary mt-2">This step is under construction.</p>
                </div>
            )
    }
}

export function Onboarding(): JSX.Element {
    const { currentStepKey, currentStepIndex, totalSteps, isFirstStep, name } = useValues(onboardingLogic)
    const { nextStep, previousStep } = useActions(onboardingLogic)

    const ctaLabel = currentStepKey === 'create_org' ? 'Create organization' : 'Continue'
    const ctaDisabledReason =
        currentStepKey === 'create_org' && !name.trim() ? 'Enter your name to continue' : undefined
    const showFooter = currentStepKey !== 'done'

    return (
        <div className="flex h-full w-full flex-col bg-primary">
            {/* Two-column area: form + preview */}
            <div className="flex min-h-0 flex-1">
                {/* Left: form column */}
                <div className="flex min-w-0 flex-1 flex-col">
                    <div className="shrink-0 flex items-center px-5 pt-6 sm:px-8 lg:px-11">
                        <Logo style={{ height: '1.5rem', width: 'auto' }} />
                    </div>
                    <div className="flex-1 overflow-y-auto px-5 py-7 sm:px-8 lg:px-11">
                        <StepBody stepKey={currentStepKey} />
                    </div>
                </div>
                {/* Right: live-preview pane — hidden on narrow screens; dotted paper-desk backdrop (theme-adaptive). */}
                <div className="hidden shrink-0 items-center justify-center border-l border-primary bg-surface-secondary bg-[image:radial-gradient(var(--border-3000)_1.4px,transparent_1.4px)] bg-[length:16px_16px] p-8 lg:flex lg:w-[42%] xl:w-2/5">
                    <OnboardingPreview />
                </div>
            </div>
            {/* Footer nav — full viewport width, spanning both columns */}
            {showFooter && (
                <div className="shrink-0 flex items-center gap-4 border-t border-primary px-5 py-4 sm:px-8 lg:px-11">
                    {!isFirstStep && (
                        <LemonButton type="tertiary" icon={<IconArrowLeft />} onClick={() => previousStep()}>
                            Back
                        </LemonButton>
                    )}
                    <div className="ml-auto flex items-center gap-4">
                        <span className="text-muted text-xs tabular-nums">
                            {currentStepIndex + 1} / {totalSteps}
                        </span>
                        <LemonButton
                            type="primary"
                            sideIcon={<IconArrowRight />}
                            disabledReason={ctaDisabledReason}
                            onClick={() => nextStep()}
                        >
                            {ctaLabel}
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}
