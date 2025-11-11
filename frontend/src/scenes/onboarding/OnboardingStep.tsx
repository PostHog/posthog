import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React from 'react'

import { IconArrowRight, IconChevronRight } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'

import { OnboardingStepKey } from '~/types'

import { breadcrumbExcludeSteps, onboardingLogic, stepKeyToTitle } from './onboardingLogic'

export const OnboardingStep = ({
    stepKey,
    title,
    subtitle,
    children,
    showSkip = false,
    showHelpButton = false,
    onSkip,
    onContinue,
    continueText,
    continueOverride,
    continueDisabledReason,
    hideHeader,
    breadcrumbHighlightName,
    fullWidth = false,
    actions,
}: {
    stepKey: OnboardingStepKey
    title: string
    subtitle?: string
    children: React.ReactNode
    showSkip?: boolean
    showHelpButton?: boolean
    onSkip?: () => void
    onContinue?: () => void
    continueText?: string
    continueOverride?: JSX.Element
    continueDisabledReason?: string
    hideHeader?: boolean
    breadcrumbHighlightName?: OnboardingStepKey
    fullWidth?: boolean
    actions?: JSX.Element
}): JSX.Element => {
    const { hasNextStep, onboardingStepKeys, currentOnboardingStep } = useValues(onboardingLogic)
    const { completeOnboarding, goToNextStep, setStepKey } = useActions(onboardingLogic)
    const { openSupportForm } = useActions(supportLogic)

    if (!stepKey) {
        throw new Error('stepKey is required in any OnboardingStep')
    }
    const breadcrumbStepKeys = onboardingStepKeys.filter((stepKey) => !breadcrumbExcludeSteps.includes(stepKey))

    return (
        <>
            <div className="pb-2">
                <div className={`text-secondary max-w-screen-md mx-auto ${hideHeader && 'hidden'}`}>
                    <div
                        className="flex items-center justify-start gap-x-3 px-2 shrink-0 w-full"
                        data-attr="onboarding-breadcrumbs"
                    >
                        {breadcrumbStepKeys.map((stepName, idx) => {
                            const highlightStep = [
                                currentOnboardingStep?.props.stepKey,
                                breadcrumbHighlightName,
                            ].includes(stepName)
                            return (
                                <React.Fragment key={`stepKey-${idx}`}>
                                    <Link
                                        className={`text-sm ${highlightStep && 'font-bold'} font-bold`}
                                        data-text={stepKeyToTitle(stepName)}
                                        key={stepName}
                                        onClick={() => setStepKey(stepName)}
                                    >
                                        <span className={`text-sm ${!highlightStep && 'text-muted'}`}>
                                            {stepKeyToTitle(stepName)}
                                        </span>
                                    </Link>
                                    {breadcrumbStepKeys.length > 1 && idx !== breadcrumbStepKeys.length - 1 && (
                                        <IconChevronRight className="text-xl" />
                                    )}
                                </React.Fragment>
                            )
                        })}
                    </div>
                    <div className="flex flex-row justify-between items-center gap-2 mt-3">
                        <h1 className={`font-bold m-0 px-2 ${fullWidth && 'text-center'}`}>
                            {title || stepKeyToTitle(currentOnboardingStep?.props.stepKey)}
                        </h1>
                        {actions && <div className="flex flex-row gap-2">{actions}</div>}
                    </div>
                </div>
            </div>
            <div className={clsx('p-2', !fullWidth && 'max-w-screen-md mx-auto')}>
                {subtitle && (
                    <div className="max-w-screen-md mx-auto">
                        <p>{subtitle}</p>
                    </div>
                )}
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
                                onContinue?.()
                                !hasNextStep ? completeOnboarding() : goToNextStep()
                            }}
                            sideIcon={hasNextStep ? <IconArrowRight /> : null}
                            disabledReason={continueDisabledReason}
                        >
                            {continueText ? continueText : !hasNextStep ? 'Finish' : 'Next'}
                        </LemonButton>
                    )}
                </div>
            </div>
        </>
    )
}
