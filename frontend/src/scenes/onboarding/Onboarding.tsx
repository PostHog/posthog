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
import { ProductKey } from '~/types'

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
    const onboardingViews = {
        [ProductKey.PRODUCT_ANALYTICS]: ProductAnalyticsOnboarding,
        [ProductKey.SESSION_REPLAY]: SessionReplayOnboarding,
        [ProductKey.FEATURE_FLAGS]: FeatureFlagsOnboarding,
    }
    const OnboardingView = onboardingViews[productKey]
    return OnboardingView ? <OnboardingView /> : <></>
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
