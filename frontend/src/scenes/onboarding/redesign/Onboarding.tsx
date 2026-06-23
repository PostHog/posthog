import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconArrowRight } from '@posthog/icons'
import { LemonButton, ProfilePicture } from '@posthog/lemon-ui'

import { PostHogLogo } from 'lib/brand/v2'
import { userLogic } from 'scenes/userLogic'

import { onboardingLogic, type OnboardingStepKey } from './onboardingLogic'
import { OnboardingPreview } from './preview/OnboardingPreview'
import { CompanyStep } from './steps/CompanyStep'
import { CreateOrgStep } from './steps/CreateOrgStep'
import { InstallStep } from './steps/InstallStep'

// Titles for steps whose bodies are not built yet. Each step PR replaces its placeholder with the real component.
const PLACEHOLDER_TITLES: Partial<Record<OnboardingStepKey, string>> = {
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
        case 'install':
            return <InstallStep />
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
    const { currentStepKey, currentStepIndex, totalSteps, isFirstStep, name, previewFocus } = useValues(onboardingLogic)
    const { user } = useValues(userLogic)
    const { nextStep, previousStep } = useActions(onboardingLogic)

    const ctaLabel = currentStepKey === 'create_org' ? 'Create organization' : 'Continue'
    const ctaDisabledReason =
        currentStepKey === 'create_org' && !name.trim() ? 'Enter your name to continue' : undefined
    const showFooter = currentStepKey !== 'done'

    const zoomStyle: React.CSSProperties = (() => {
        const transition = 'transform 0.12s linear'
        if (previewFocus === 'orgName') {
            return {
                transform: 'scale(1.9)',
                transformOrigin: 'left top',
                transition,
            }
        }
        if (previewFocus === 'userName') {
            return {
                transform: 'translate(-33%, -4%) scale(1.8)',
                transformOrigin: 'left top',
                transition,
            }
        }
        return {
            transform: 'translate(0%, -4.5%) scale(1.1)',
            transformOrigin: 'left top',
            transition,
        }
    })()

    return (
        <div className="flex h-full w-full flex-col bg-primary">
            {/* Two-column area: form + preview */}
            <div className="flex min-h-0 flex-1">
                {/* Left: form column */}
                <div className="flex min-w-0 flex-1 flex-col">
                    <div className="shrink-0 flex items-center px-5 pt-6 sm:px-8 lg:px-11">
                        <PostHogLogo className="h-6 w-auto" />
                        <ProfilePicture user={user} size="md" className="ml-auto" />
                    </div>
                    <div className="flex-1 overflow-y-auto px-5 py-7 sm:px-8 lg:px-11">
                        <StepBody stepKey={currentStepKey} />
                    </div>
                </div>
                {/* Right: live-preview pane — hidden on narrow screens; dotted paper-desk backdrop (theme-adaptive). */}
                {/* The preview is uniformly scaled up (zoomed) and anchored left, bleeding off the right edge (cropped). */}
                <div className="hidden shrink-0 items-center overflow-hidden border-l border-primary bg-surface-secondary bg-[image:radial-gradient(var(--border-3000)_1.4px,transparent_1.4px)] bg-[length:16px_16px] py-8 pl-8 lg:flex lg:w-1/2 xl:w-[45%]">
                    {/* h ≈ 1/scale and w sized so that, after scaling, the height fills and the width overflows (cropped). */}
                    <div className="h-[91%] w-[102%] shrink-0" style={zoomStyle}>
                        <OnboardingPreview />
                    </div>
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
