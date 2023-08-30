import { SceneExport } from 'scenes/sceneTypes'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'
import { onboardingLogic } from './onboardingLogic'
import { SDKs } from './sdks/SDKs'
import { OnboardingProductIntro } from './OnboardingProductIntro'
import { OnboardingStep } from './OnboardingStep'

export const scene: SceneExport = {
    component: Onboarding,
    logic: onboardingLogic,
}

const OnboardingWrapper = ({ children }: { children: React.ReactNode }): JSX.Element => {
    const { onboardingStep } = useValues(onboardingLogic)
    const { setTotalOnboardingSteps } = useActions(onboardingLogic)

    useEffect(() => {
        setTotalOnboardingSteps(Array.isArray(children) ? children.length : 1)
    }, [children])

    if (!Array.isArray(children)) {
        return children as JSX.Element
    }
    return children ? (children[onboardingStep - 1] as JSX.Element) : <></>
}

const ProductAnalyticsOnboarding = (): JSX.Element => {
    const { product } = useValues(onboardingLogic)

    return product ? (
        <OnboardingWrapper>
            <OnboardingProductIntro product={product} />
            <SDKs usersAction="collecting events" />
            <OnboardingStep title="my onboarding step" subtitle="my onboarding subtitle">
                <div>my onboarding content</div>
            </OnboardingStep>
        </OnboardingWrapper>
    ) : (
        <></>
    )
}
const SessionReplayOnboarding = (): JSX.Element => {
    const { product } = useValues(onboardingLogic)

    return product ? (
        <OnboardingWrapper>
            <OnboardingProductIntro product={product} />
            <SDKs usersAction="recording sessions" />
        </OnboardingWrapper>
    ) : (
        <></>
    )
}
const FeatureFlagsOnboarding = (): JSX.Element => {
    const { product } = useValues(onboardingLogic)

    return product ? (
        <OnboardingWrapper>
            <OnboardingProductIntro product={product} />
            <SDKs usersAction="loading flags" />
        </OnboardingWrapper>
    ) : (
        <></>
    )
}

const getOnboarding = (productKey: string): JSX.Element => {
    if (productKey === 'product_analytics') {
        return <ProductAnalyticsOnboarding />
    } else if (productKey === 'session_replay') {
        return <SessionReplayOnboarding />
    } else if (productKey === 'feature_flags') {
        return <FeatureFlagsOnboarding />
    }
    return <></>
}

export function Onboarding(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { product } = useValues(onboardingLogic)

    useEffect(() => {
        if (featureFlags[FEATURE_FLAGS.PRODUCT_SPECIFIC_ONBOARDING] !== 'test') {
            location.href = urls.ingestion()
        }
    }, [])

    return product ? getOnboarding(product.type) : null
}
