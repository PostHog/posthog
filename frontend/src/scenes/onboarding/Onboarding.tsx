import { SceneExport } from 'scenes/sceneTypes'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { OnboardingStepKey, onboardingLogic } from './onboardingLogic'
import { SDKs } from './sdks/SDKs'
import { ProductKey } from '~/types'
import { ProductAnalyticsSDKInstructions } from './sdks/product-analytics/ProductAnalyticsSDKInstructions'
import { SessionReplaySDKInstructions } from './sdks/session-replay/SessionReplaySDKInstructions'
import { OnboardingBillingStep } from './OnboardingBillingStep'
import { OnboardingOtherProductsStep } from './OnboardingOtherProductsStep'
import { OnboardingVerificationStep } from './OnboardingVerificationStep'
import { FeatureFlagsSDKInstructions } from './sdks/feature-flags/FeatureFlagsSDKInstructions'
import { SurveysSDKInstructions } from './sdks/surveys/SurveysSDKInstructions'

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
