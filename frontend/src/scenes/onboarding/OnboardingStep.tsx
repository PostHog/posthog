import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { IconArrowRight, IconChevronRight } from 'lib/lemon-ui/icons'
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
    continueOverride?: JSX.Element
    hideHeader?: boolean
}): JSX.Element => {
    const { hasNextStep, onboardingStepNames, currentOnboardingStep } = useValues(onboardingLogic)
    const { completeOnboarding, goToNextStep, setStepKey } = useActions(onboardingLogic)
    const { openSupportForm } = useActions(supportLogic)

    if (!stepKey) {
        throw new Error('stepKey is required in any OnboardingStep')
    }

    return (
        <>
            <div className="pb-2">
                <div className={`flex justify-between items-center text-muted ${hideHeader && 'hidden'}`}>
                    <h1 className="font-bold m-0 pl-2">
                        {title || stepKeyToTitle(currentOnboardingStep?.props.stepKey)}
                    </h1>
                    <div className="flex items-center gap-x-3">
                        {onboardingStepNames.map((stepName, idx) => {
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
                                    {onboardingStepNames.length > 1 && idx !== onboardingStepNames.length - 1 && (
                                        <IconChevronRight className="text-xl" />
                                    )}
                                </React.Fragment>
                            )
                        })}
                    </div>
                </div>
            </div>
            <div className="p-2">
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
                            onClick={() => {
                                continueAction && continueAction()
                                !hasNextStep ? completeOnboarding() : goToNextStep()
                            }}
                            sideIcon={hasNextStep ? <IconArrowRight /> : null}
                        >
                            {!hasNextStep ? 'Finish' : 'Next'}
                        </LemonButton>
                    )}
                </div>
            </div>
        </>
    )
}
