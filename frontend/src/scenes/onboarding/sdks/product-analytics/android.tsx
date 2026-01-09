import { AndroidInstallation } from '@posthog/shared-onboarding/product-analytics/android'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { SDKKey } from '~/types'

import { AdvertiseMobileReplay } from '../session-replay/SessionReplaySDKInstructions'

export function ProductAnalyticsAndroidInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <AndroidInstallation />
            <AdvertiseMobileReplay context="product-analytics-onboarding" sdkKey={SDKKey.ANDROID} />
        </OnboardingDocsContentWrapper>
    )
}
