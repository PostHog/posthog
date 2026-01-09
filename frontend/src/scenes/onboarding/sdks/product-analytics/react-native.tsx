import { ReactNativeInstallation } from '@posthog/shared-onboarding/product-analytics/react-native'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { SDKKey } from '~/types'

import { AdvertiseMobileReplay } from '../session-replay/SessionReplaySDKInstructions'

export function ProductAnalyticsRNInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <ReactNativeInstallation />
            <AdvertiseMobileReplay context="product-analytics-onboarding" sdkKey={SDKKey.REACT_NATIVE} />
        </OnboardingDocsContentWrapper>
    )
}
