import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import { IconArrowLeft, IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { OnboardingStepKey } from '~/types'

import { OnboardingBreadcrumbs } from './OnboardingBreadcrumbs'
import { stepKeyToTitle } from './onboardingFlowUtils'
import { onboardingLogic } from './onboardingLogic'

export const OnboardingStep = ({
    stepKey,
    title,
    subtitle,
    children,
    showContinue = true,
    showSkip = false,
    showHelpButton = false,
    onSkip,
    onContinue,
    continueText,
    continueDisabledReason,
    hideHeader,
    hideTitle = false,
    fullWidth = false,
    actions,
}: {
    stepKey: OnboardingStepKey
    title: string
    subtitle?: string
    children: React.ReactNode
    showContinue?: boolean
    showSkip?: boolean
    showHelpButton?: boolean
    onSkip?: () => void
    onContinue?: () => void
    continueText?: string
    continueDisabledReason?: string
    hideHeader?: boolean
    /** Hide just the <h1> title (keeps breadcrumbs and the actions slot). */
    hideTitle?: boolean
    fullWidth?: boolean
    actions?: JSX.Element
}): JSX.Element => {
    const { hasNextStep, hasPreviousStep, currentStepProductKey } = useValues(onboardingLogic)

    const { completeOnboarding, goToNextStep, goToPreviousStep } = useActions(onboardingLogic)
    const { reportOnboardingStepCompleted, reportOnboardingStepSkipped } = useActions(eventUsageLogic)
    const { openSupportForm } = useActions(supportLogic)

    const advance: () => void = !hasNextStep ? completeOnboarding : goToNextStep

    // advance() kicks off an async URL change that produces no immediate DOM mutation near the button, so without
    // this posthog-js flags the click as a dead click. Setting a pending state gives instant visual feedback.
    const [pendingAdvance, setPendingAdvance] = useState<'skip' | 'continue' | null>(null)

    // On the happy path the component unmounts as soon as navigation happens. If advance() fails or navigation is
    // blocked, this safety net clears the pending state so the buttons don't stay stuck loading/disabled forever.
    useEffect(() => {
        if (!pendingAdvance) {
            return
        }
        const timeout = setTimeout(() => setPendingAdvance(null), 5000)
        return () => clearTimeout(timeout)
    }, [pendingAdvance])

    const skip = (): void => {
        setPendingAdvance('skip')
        reportOnboardingStepSkipped(stepKey, currentStepProductKey ?? undefined)
        onSkip?.()
        advance()
    }

    // The first step has no previous step in the flow, so Back returns to product selection.
    const back = (): void => {
        if (hasPreviousStep) {
            goToPreviousStep()
        } else {
            router.actions.push(urls.onboarding())
        }
    }

    const next = (): void => {
        setPendingAdvance('continue')
        reportOnboardingStepCompleted(stepKey, currentStepProductKey ?? undefined)
        onContinue?.()
        advance()
    }

    return (
        <>
            <div className="pb-2">
                <div className={`text-secondary max-w-screen-md mx-auto ${hideHeader && 'hidden'}`}>
                    <OnboardingBreadcrumbs />
                    <div className="flex flex-col sm:flex-row sm:justify-between sm:items-center items-start gap-2 mt-3 px-4 sm:px-0">
                        {!hideTitle && (
                            <h1 className={clsx('font-bold m-0 px-0 sm:px-2 sm:shrink-0', fullWidth && 'text-center')}>
                                {title || stepKeyToTitle(stepKey)}
                            </h1>
                        )}
                        {actions && (
                            <div className="flex flex-row flex-wrap sm:flex-nowrap gap-2 min-w-0">{actions}</div>
                        )}
                    </div>
                </div>
            </div>
            <div className={clsx('px-4 py-2 sm:p-2', !fullWidth && 'max-w-screen-md mx-auto')}>
                {subtitle && (
                    <div className="max-w-screen-md mx-auto">
                        <p>{subtitle}</p>
                    </div>
                )}
                {children}
                <div className="mt-8 flex flex-wrap justify-between gap-2">
                    <LemonButton
                        type="secondary"
                        icon={<IconArrowLeft />}
                        onClick={back}
                        disabledReason={pendingAdvance ? 'Completing…' : undefined}
                        data-attr="onboarding-back-button"
                    >
                        Back
                    </LemonButton>
                    <div className="flex flex-wrap justify-end gap-2">
                        {showHelpButton && (
                            <LemonButton type="secondary" onClick={() => openSupportForm({ kind: 'support' })}>
                                Need help?
                            </LemonButton>
                        )}
                        {showSkip && (
                            <LemonButton
                                type="secondary"
                                onClick={skip}
                                loading={pendingAdvance === 'skip'}
                                disabledReason={pendingAdvance === 'continue' ? 'Completing…' : undefined}
                                data-attr="onboarding-skip-button"
                            >
                                Skip {!hasNextStep ? 'and finish' : 'for now'}
                            </LemonButton>
                        )}
                        {showContinue && (
                            <LemonButton
                                type="primary"
                                status="alt"
                                data-attr="onboarding-continue"
                                onClick={next}
                                loading={pendingAdvance === 'continue'}
                                sideIcon={hasNextStep ? <IconArrowRight /> : null}
                                disabledReason={pendingAdvance === 'skip' ? 'Completing…' : continueDisabledReason}
                            >
                                {continueText ? continueText : !hasNextStep ? 'Finish' : 'Next'}
                            </LemonButton>
                        )}
                    </div>
                </div>
            </div>
        </>
    )
}
