import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/types'

import { OnboardingBillingStep } from './OnboardingBillingStep'
import { onboardingLogic, OnboardingStepKey } from './onboardingLogic'
import { OnboardingOtherProductsStep } from './OnboardingOtherProductsStep'
import { OnboardingVerificationStep } from './OnboardingVerificationStep'
import { FeatureFlagsSDKInstructions } from './sdks/feature-flags/FeatureFlagsSDKInstructions'
import { ProductAnalyticsSDKInstructions } from './sdks/product-analytics/ProductAnalyticsSDKInstructions'
import { SDKs } from './sdks/SDKs'
import { SessionReplaySDKInstructions } from './sdks/session-replay/SessionReplaySDKInstructions'
import { SurveysSDKInstructions } from './sdks/surveys/SurveysSDKInstructions'
import { OnboardingProductConfiguration } from './OnboardingProductConfiguration'
import { teamLogic } from 'scenes/teamLogic'

export const scene: SceneExport = {
    component: Onboarding,
    logic: onboardingLogic,
}

/**
 * Wrapper for custom onboarding content. This automatically includes the product intro and billing step.
 */
const OnboardingWrapper = ({ children }: { children: React.ReactNode }): JSX.Element => {
    const { currentOnboardingStep, shouldShowBillingStep, shouldShowOtherProductsStep } = useValues(onboardingLogic)
    const { setAllOnboardingSteps } = useActions(onboardingLogic)
    const { product } = useValues(onboardingLogic)
    const [allSteps, setAllSteps] = useState<JSX.Element[]>([])

    useEffect(() => {
        createAllSteps()
    }, [children])

    useEffect(() => {
        if (!allSteps.length) {
            return
        }
        setAllOnboardingSteps(allSteps)
    }, [allSteps])

    if (!product || !children) {
        return <></>
    }

    const createAllSteps = (): void => {
        let steps = []
        if (Array.isArray(children)) {
            steps = [...children]
        } else {
            steps = [children as JSX.Element]
        }
        if (shouldShowBillingStep) {
            const BillingStep = <OnboardingBillingStep product={product} stepKey={OnboardingStepKey.BILLING} />
            steps = [...steps, BillingStep]
        }
        if (shouldShowOtherProductsStep) {
            const OtherProductsStep = <OnboardingOtherProductsStep stepKey={OnboardingStepKey.OTHER_PRODUCTS} />
            steps = [...steps, OtherProductsStep]
        }
        setAllSteps(steps)
    }

    return (currentOnboardingStep as JSX.Element) || <></>
}

const ProductAnalyticsOnboarding = (): JSX.Element => {
    const { currentTeam } = useValues(teamLogic)

    return (
        <OnboardingWrapper>
            <SDKs
                usersAction="collecting events"
                sdkInstructionMap={ProductAnalyticsSDKInstructions}
                stepKey={OnboardingStepKey.SDKS}
            />
            <OnboardingVerificationStep
                listeningForName="event"
                teamPropertyToVerify="ingested_event"
                stepKey={OnboardingStepKey.VERIFY}
            />
            <OnboardingProductConfiguration
                stepKey={OnboardingStepKey.PRODUCT_CONFIGURATION}
                options={[
                    {
                        title: 'Autocapture frontend interactions',
                        description: `If you use our JavaScript or React Native libraries, we'll automagically 
                            capture frontend interactions like pageviews, clicks, and more. Fine-tune what you 
                            capture directly in your code snippet.`,
                        teamProperty: 'autocapture_opt_out',
                        value: !currentTeam?.autocapture_opt_out,
                        type: 'toggle',
                        inverseToggle: true,
                    },
                ]}
            />
        </OnboardingWrapper>
    )
}
const SessionReplayOnboarding = (): JSX.Element => {
    return (
        <OnboardingWrapper>
            <SDKs
                usersAction="recording sessions"
                sdkInstructionMap={SessionReplaySDKInstructions}
                subtitle="Choose the framework your frontend is built on, or use our all-purpose JavaScript library. If you already have the snippet installed, you can skip this step!"
                stepKey={OnboardingStepKey.SDKS}
            />
        </OnboardingWrapper>
    )
}
const FeatureFlagsOnboarding = (): JSX.Element => {
    return (
        <OnboardingWrapper>
            <SDKs
                usersAction="loading flags & experiments"
                sdkInstructionMap={FeatureFlagsSDKInstructions}
                subtitle="Choose the framework where you want to use feature flags and/or run experiments, or use our all-purpose JavaScript library. If you already have the snippet installed, you can skip this step!"
                stepKey={OnboardingStepKey.SDKS}
            />
        </OnboardingWrapper>
    )
}

const SurveysOnboarding = (): JSX.Element => {
    return (
        <OnboardingWrapper>
            <SDKs
                usersAction="taking surveys"
                sdkInstructionMap={SurveysSDKInstructions}
                subtitle="Choose the framework your frontend is built on, or use our all-purpose JavaScript library. If you already have the snippet installed, you can skip this step!"
                stepKey={OnboardingStepKey.SDKS}
            />
        </OnboardingWrapper>
    )
}

export function Onboarding(): JSX.Element | null {
    const { product } = useValues(onboardingLogic)

    if (!product) {
        return <></>
    }
    const onboardingViews = {
        [ProductKey.PRODUCT_ANALYTICS]: ProductAnalyticsOnboarding,
        [ProductKey.SESSION_REPLAY]: SessionReplayOnboarding,
        [ProductKey.FEATURE_FLAGS]: FeatureFlagsOnboarding,
        [ProductKey.SURVEYS]: SurveysOnboarding,
    }
    const OnboardingView = onboardingViews[product.type]

    return <OnboardingView />
}
