import './onboarding.scss'

import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { PhonePairHogs } from 'lib/components/hedgehogs'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { IconArrowLeft, IconArrowRight } from 'lib/lemon-ui/icons'
import React from 'react'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/types'

import { getProductUri, onboardingLogic, OnboardingStepKey, stepKeyToTitle } from './onboardingLogic'

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
    backActionOverride,
    hedgehog,
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
    backActionOverride?: () => void
    hedgehog?: JSX.Element
}): JSX.Element => {
    const {
        hasNextStep,
        onboardingStepNames,
        totalOnboardingSteps,
        hasPreviousStep,
        productKey,
        isFirstProductOnboarding,
        currentOnboardingStep,
    } = useValues(onboardingLogic)
    const { completeOnboarding, goToNextStep, setStepKey, goToPreviousStep } = useActions(onboardingLogic)
    const { openSupportForm } = useActions(supportLogic)
    const hedgehogToRender = React.cloneElement(hedgehog || <PhonePairHogs />, {
        className: 'h-full w-full',
    })

    if (!stepKey) {
        throw new Error('stepKey is required in any OnboardingStep')
    }

    return (
        //             <LemonButton
        //                 icon={<IconArrowLeft />}
        //                 onClick={() =>
        //                     backActionOverride
        //                         ? backActionOverride()
        //                         : hasPreviousStep
        //                         ? goToPreviousStep()
        //                         : !isFirstProductOnboarding
        //                         ? router.actions.push(getProductUri(productKey as ProductKey))
        //                         : router.actions.push(urls.products())
        //                 }
        //             >
        //                 Back
        //             </LemonButton>
        <>
            <div className="pb-10">
                <div className="flex justify-between items-center">
                    <h1 className="font-bold m-0 pl-2">
                        {title || stepKeyToTitle(currentOnboardingStep?.props.stepKey)}
                    </h1>
                    <div className="flex gap-2 items-center">
                        {onboardingStepNames.map((stepName, idx) => {
                            return (
                                <React.Fragment key={idx}>
                                    <div
                                        className={`onboardingCrumb ${
                                            currentOnboardingStep?.props.stepKey === stepName && 'font-bold'
                                        }`}
                                        key={stepName}
                                        onClick={() => setStepKey(stepName)}
                                    >
                                        {stepKeyToTitle(stepName)}
                                    </div>
                                    {onboardingStepNames.length > 1 && idx !== onboardingStepNames.length - 1 && (
                                        <div key={`${stepName}-separator`} className="onboardingCrumbSeparator" />
                                    )}
                                </React.Fragment>
                            )
                        })}
                    </div>
                </div>
            </div>
            <div className="p-2">
                {hedgehog && <div className="-mt-20 absolute right-4 h-16">{hedgehogToRender}</div>}

                <p>{subtitle}</p>
                {children}
                <div className="mt-8 flex justify-start gap-x-2">
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
        // </BridgePage>
    )
}
