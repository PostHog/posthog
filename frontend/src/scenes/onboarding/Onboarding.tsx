import { SceneExport } from 'scenes/sceneTypes'
import { useValues } from 'kea'
import { useEffect } from 'react'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'
import { onboardingLogic } from './onboardingLogic'
import { SDKs } from './sdks/SDKs'
import { OnboardingProductIntro } from './OnboardingProductIntro'

export const scene: SceneExport = {
    component: Onboarding,
    logic: onboardingLogic,
}

const OnboardingWrapper = ({ children }: { children: React.ReactNode }): JSX.Element => {
    const { onboardingStep } = useValues(onboardingLogic)
    if (!Array.isArray(children)) {
        return children as JSX.Element
    }
    return children ? (children[onboardingStep] as JSX.Element) : <></>
}

const ProductAnalyticsOnboarding = (): JSX.Element => {
    const { product } = useValues(onboardingLogic)

    return product ? (
        <OnboardingWrapper>
            <OnboardingProductIntro product={product} />
            <SDKs />
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
            <SDKs />
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
