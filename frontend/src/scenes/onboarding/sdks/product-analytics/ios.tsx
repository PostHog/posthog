import { IOSInstallation } from '@posthog/shared-onboarding/product-analytics/ios'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { SDKKey } from '~/types'

import { AdvertiseMobileReplay } from '../session-replay/SessionReplaySDKInstructions'

export function ProductAnalyticsIOSInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <IOSInstallation />
            <AdvertiseMobileReplay context="product-analytics-onboarding" sdkKey={SDKKey.IOS} />
        </OnboardingDocsContentWrapper>
    )
}
