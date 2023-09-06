import { SceneExport } from 'scenes/sceneTypes'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'
import { onboardingLogic } from './onboardingLogic'
import { SDKs } from './sdks/SDKs'
import { OnboardingProductIntro } from './OnboardingProductIntro'
import { OnboardingStep } from './OnboardingStep'
import { ProductKey } from '~/types'
import { ProductAnalyticsSDKInstructions } from './sdks/product-analytics/ProductAnalyticsSDKInstructions'
import { SessionReplaySDKInstructions } from './sdks/session-replay/SessionReplaySDKInstructions'

export const scene: SceneExport = {
    component: Onboarding,
    logic: onboardingLogic,
}

const OnboardingWrapper = ({ children }: { children: React.ReactNode }): JSX.Element => {
    const { onboardingStep } = useValues(onboardingLogic)
    const { setTotalOnboardingSteps } = useActions(onboardingLogic)
    const { product } = useValues(onboardingLogic)
    const [allSteps, setAllSteps] = useState<JSX.Element[]>([])

    useEffect(() => {
        createAllSteps()
    }, [children])

    useEffect(() => {
        setTotalOnboardingSteps(allSteps.length)
    }, [allSteps])

    if (!product || !children) {
        return <></>
    }

    const createAllSteps = (): void => {
        const ProductIntro = <OnboardingProductIntro product={product} />
        if (Array.isArray(children)) {
            setAllSteps([ProductIntro, ...children])
        } else {
            setAllSteps([ProductIntro, children as JSX.Element])
        }
        setTotalOnboardingSteps(Array.isArray(children) ? children.length : 1)
    }

    return (allSteps[onboardingStep - 1] as JSX.Element) || <></>
}

const ProductAnalyticsOnboarding = (): JSX.Element => {
    return (
        <OnboardingWrapper>
            <SDKs usersAction="collecting events" sdkInstructionMap={ProductAnalyticsSDKInstructions} />
            <OnboardingStep title="my onboarding step" subtitle="my onboarding subtitle">
                <div>my onboarding content</div>
            </OnboardingStep>
        </OnboardingWrapper>
    )
}
const SessionReplayOnboarding = (): JSX.Element => {
    return (
        <OnboardingWrapper>
            <SDKs
                usersAction="recording sessions"
                sdkInstructionMap={SessionReplaySDKInstructions}
                subtitle="Choose the framework your frontend is built on, or use our all-purpose JavaScript library."
            />
        </OnboardingWrapper>
    )
}
const FeatureFlagsOnboarding = (): JSX.Element => {
    return <OnboardingWrapper>{/* <SDKs usersAction="loading flags" /> */}</OnboardingWrapper>
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
