import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { PhonePairHogs } from 'lib/components/hedgehogs'
import { IconArrowLeft, IconArrowRight } from 'lib/lemon-ui/icons'
import React from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/types'

import { getProductUri, onboardingLogic, OnboardingStepKey } from './onboardingLogic'

export const OnboardingStep = ({
    stepKey,
    title,
    subtitle,
    children,
    showSkip = false,
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
    onSkip?: () => void
    continueAction?: () => void
    continueOverride?: JSX.Element
    backActionOverride?: () => void
    hedgehog?: JSX.Element
}): JSX.Element => {
    const { hasNextStep, hasPreviousStep, productKey } = useValues(onboardingLogic)
    const { completeOnboarding, goToNextStep, goToPreviousStep } = useActions(onboardingLogic)
    const { currentTeam } = useValues(teamLogic)
    const isFirstProductOnboarding = !Object.keys(currentTeam?.has_completed_onboarding_for || {}).some(
        (key) => currentTeam?.has_completed_onboarding_for?.[key] === true
    )

    const hedgehogToRender = React.cloneElement(hedgehog || <PhonePairHogs />, {
        className: 'h-full w-full',
    })

    if (!stepKey) {
        throw new Error('stepKey is required in any OnboardingStep')
    }

    return (
        <BridgePage
            view="onboarding-step"
            noLogo
            hedgehog={false}
            fixedWidth={false}
            header={
                <div className="mb-4">
                    <LemonButton
                        icon={<IconArrowLeft />}
                        onClick={() =>
                            backActionOverride
                                ? backActionOverride()
                                : hasPreviousStep
                                ? goToPreviousStep()
                                : !isFirstProductOnboarding
                                ? router.actions.push(getProductUri(productKey as ProductKey))
                                : router.actions.push(urls.products())
                        }
                    >
                        Back
                    </LemonButton>
                </div>
            }
        >
            <div className="max-w-192">
                {hedgehog && <div className="-mt-20 absolute right-4 h-16">{hedgehogToRender}</div>}

                <h1 className="font-bold">{title}</h1>
                <p>{subtitle}</p>
                {children}
                <div className="mt-8 flex justify-end gap-x-2">
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
                            {!hasNextStep ? 'Finish' : 'Continue'}
                        </LemonButton>
                    )}
                </div>
            </div>
        </BridgePage>
    )
}
