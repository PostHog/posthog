import { SceneExport } from 'scenes/sceneTypes'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'
import { onboardingLogic } from './onboardingLogic'
import { SDKs } from './sdks/SDKs'
import { OnboardingProductIntro } from './OnboardingProductIntro'
import { ProductKey } from '~/types'
import { ProductAnalyticsSDKInstructions } from './sdks/product-analytics/ProductAnalyticsSDKInstructions'
import { SessionReplaySDKInstructions } from './sdks/session-replay/SessionReplaySDKInstructions'
import { OnboardingBillingStep } from './OnboardingBillingStep'
import { OnboardingOtherProductsStep } from './OnboardingOtherProductsStep'
import { teamLogic } from 'scenes/teamLogic'
import { OnboardingVerificationStep } from './OnboardingVerificationStep'
import { FeatureFlagsSDKInstructions } from './sdks/feature-flags/FeatureFlagsSDKInstructions'

export const scene: SceneExport = {
    component: Onboarding,
    logic: onboardingLogic,
}

/**
 * Wrapper for custom onboarding content. This automatically includes the product intro and billing step.
 */
const OnboardingWrapper = ({ children, onStart }: { children: React.ReactNode; onStart?: () => void }): JSX.Element => {
    const { currentOnboardingStepNumber, shouldShowBillingStep } = useValues(onboardingLogic)
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
        const ProductIntro = <OnboardingProductIntro product={product} onStart={onStart} />
        const OtherProductsStep = <OnboardingOtherProductsStep />
        let steps = []
        if (Array.isArray(children)) {
            steps = [ProductIntro, ...children]
        } else {
            steps = [ProductIntro, children as JSX.Element]
        }
        if (shouldShowBillingStep) {
            const BillingStep = <OnboardingBillingStep product={product} />
            steps = [...steps, BillingStep]
        }
        steps = [...steps, OtherProductsStep]
        setAllSteps(steps)
    }

    return (allSteps[currentOnboardingStepNumber - 1] as JSX.Element) || <></>
}

const ProductAnalyticsOnboarding = (): JSX.Element => {
    return (
        <OnboardingWrapper>
            <SDKs usersAction="collecting events" sdkInstructionMap={ProductAnalyticsSDKInstructions} />
            <OnboardingVerificationStep listeningForName="event" teamPropertyToVerify="ingested_event" />
        </OnboardingWrapper>
    )
}
const SessionReplayOnboarding = (): JSX.Element => {
    const { updateCurrentTeam } = useActions(teamLogic)
    return (
        <OnboardingWrapper
            onStart={() => {
                updateCurrentTeam({
                    session_recording_opt_in: true,
                    capture_console_log_opt_in: true,
                    capture_performance_opt_in: true,
                })
            }}
        >
            <SDKs
                usersAction="recording sessions"
                sdkInstructionMap={SessionReplaySDKInstructions}
                subtitle="Choose the framework your frontend is built on, or use our all-purpose JavaScript library. If you already have the snippet installed, you can skip this step!"
            />
        </OnboardingWrapper>
    )
}
const FeatureFlagsOnboarding = (): JSX.Element => {
    return (
        <OnboardingWrapper>
            <SDKs usersAction="loading flags" sdkInstructionMap={FeatureFlagsSDKInstructions} />
        </OnboardingWrapper>
    )
}

export function Onboarding(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { product } = useValues(onboardingLogic)

    useEffect(() => {
        if (featureFlags[FEATURE_FLAGS.PRODUCT_SPECIFIC_ONBOARDING] !== 'test') {
            location.href = urls.ingestion()
        }
    }, [])

    if (!product) {
        return <></>
    }
    const onboardingViews = {
        [ProductKey.PRODUCT_ANALYTICS]: ProductAnalyticsOnboarding,
        [ProductKey.SESSION_REPLAY]: SessionReplayOnboarding,
        [ProductKey.FEATURE_FLAGS]: FeatureFlagsOnboarding,
    }
    const OnboardingView = onboardingViews[product.type]

    return <OnboardingView />
}
