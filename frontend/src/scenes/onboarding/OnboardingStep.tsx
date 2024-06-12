import { IconArrowRight } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import React from 'react'

import { onboardingLogic, OnboardingStepKey, stepKeyToTitle } from './onboardingLogic'

export const OnboardingStep = ({
    stepKey,
    title,
    subtitle,
    children,
    showSkip = false,
    showHelpButton = false,
    onSkip,
    continueAction,
    continueText,
    continueOverride,
    hideHeader,
}: {
    stepKey: OnboardingStepKey
    title: string
    subtitle?: string
    children: React.ReactNode
    showSkip?: boolean
    showHelpButton?: boolean
    onSkip?: () => void
    continueAction?: () => void
    continueText?: string
    continueOverride?: JSX.Element
    hideHeader?: boolean
}): JSX.Element => {
    const { hasNextStep, onboardingStepKeys, currentOnboardingStep } = useValues(onboardingLogic)
    const { completeOnboarding, goToNextStep, setStepKey } = useActions(onboardingLogic)
    const { openSupportForm } = useActions(supportLogic)

    if (!stepKey) {
        throw new Error('stepKey is required in any OnboardingStep')
    }

    return (
        <>
            <div className="pb-2">
                <div className={`text-muted max-w-screen-md mx-auto ${hideHeader && 'hidden'}`}>
                    <div
                        className="flex items-center justify-start gap-x-3 px-2 shrink-0 w-full"
                        data-attr="onboarding-breadcrumbs"
                    >
                        {onboardingStepKeys.map((stepName, idx) => {
                            return (
                                <React.Fragment key={`stepKey-${idx}`}>
                                    <Link
                                        className={`text-sm ${
                                            currentOnboardingStep?.props.stepKey === stepName && 'font-bold'
                                        } font-bold`}
                                        data-text={stepKeyToTitle(stepName)}
                                        key={stepName}
                                        onClick={() => setStepKey(stepName)}
                                    >
                                        <span
                                            className={`text-sm ${
                                                currentOnboardingStep?.props.stepKey !== stepName && 'text-muted'
                                            }`}
                                        >
                                            {stepKeyToTitle(stepName)}
                                        </span>
                                    </Link>
                                    {onboardingStepKeys.length > 1 && idx !== onboardingStepKeys.length - 1 && (
                                        <IconChevronRight className="text-xl" />
                                    )}
                                </React.Fragment>
                            )
                        })}
                    </div>
                    <h1 className="font-bold m-0 mt-3 px-2">
                        {title || stepKeyToTitle(currentOnboardingStep?.props.stepKey)}
                    </h1>
                </div>
            </div>
            <div className={`${stepKey !== 'product_intro' && 'p-2 max-w-screen-md mx-auto'}`}>
                {subtitle && <p>{subtitle}</p>}
                {children}
                <div className="mt-8 flex justify-end gap-x-2">
                    {showHelpButton && (
                        <LemonButton
                            type="secondary"
                            onClick={() => openSupportForm({ kind: 'support', target_area: 'onboarding' })}
                        >
                            Need help?
                        </LemonButton>
                    )}
                    {showSkip && (
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                onSkip && onSkip()
                                !hasNextStep ? completeOnboarding() : goToNextStep()
                            }}
                            data-attr="onboarding-skip-button"
                        >
                            Skip {!hasNextStep ? 'and finish' : 'for now'}
                        </LemonButton>
                    )}
                    {continueOverride ? (
                        continueOverride
                    ) : (
                        <LemonButton
                            type="primary"
                            status="alt"
                            data-attr="onboarding-continue"
                            onClick={() => {
                                continueAction && continueAction()
                                !hasNextStep ? completeOnboarding() : goToNextStep()
                            }}
                            sideIcon={hasNextStep ? <IconArrowRight /> : null}
                        >
                            {continueText ? continueText : !hasNextStep ? 'Finish' : 'Next'}
                        </LemonButton>
                    )}
                </div>
            </div>
        </>
    )
}
