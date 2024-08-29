import { IconArrowRight } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import React from 'react'
import { urls } from 'scenes/urls'

import { breadcrumbExcludeSteps, onboardingLogic, OnboardingStepKey, stepKeyToTitle } from './onboardingLogic'
import { onboardingTemplateConfigLogic } from './productAnalyticsSteps/onboardingTemplateConfigLogic'

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
    breadcrumbHighlightName,
    fullWidth = false,
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
    breadcrumbHighlightName?: OnboardingStepKey
    fullWidth?: boolean
}): JSX.Element => {
    const { hasNextStep, onboardingStepKeys, currentOnboardingStep } = useValues(onboardingLogic)
    const { completeOnboarding, goToNextStep, setStepKey } = useActions(onboardingLogic)
    const { openSupportForm } = useActions(supportLogic)
    const { dashboardCreatedDuringOnboarding } = useValues(onboardingTemplateConfigLogic)

    if (!stepKey) {
        throw new Error('stepKey is required in any OnboardingStep')
    }
    const breadcrumbStepKeys = onboardingStepKeys.filter((stepKey) => !breadcrumbExcludeSteps.includes(stepKey))

    return (
        <>
            <div className="pb-2">
                <div className={`text-muted max-w-screen-md mx-auto ${hideHeader && 'hidden'}`}>
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
                    <h1 className="font-bold m-0 mt-3 px-2">
                        {title || stepKeyToTitle(currentOnboardingStep?.props.stepKey)}
                    </h1>
                </div>
            </div>
            <div
                className={`${stepKey !== 'product_intro' && 'p-2'} ${
                    stepKey !== 'product_intro' && !fullWidth && 'max-w-screen-md mx-auto'
                }`}
            >
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
                                !hasNextStep
                                    ? completeOnboarding(
                                          undefined,
                                          dashboardCreatedDuringOnboarding
                                              ? urls.dashboard(dashboardCreatedDuringOnboarding.id)
                                              : undefined
                                      )
                                    : goToNextStep()
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
                                !hasNextStep
                                    ? completeOnboarding(
                                          undefined,
                                          dashboardCreatedDuringOnboarding
                                              ? urls.dashboard(dashboardCreatedDuringOnboarding.id)
                                              : undefined
                                      )
                                    : goToNextStep()
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
