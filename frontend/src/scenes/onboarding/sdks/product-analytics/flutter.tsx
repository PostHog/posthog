import { FlutterInstallation } from '@posthog/shared-onboarding/product-analytics/flutter'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { SDKKey } from '~/types'

import { AdvertiseMobileReplay } from '../session-replay/SessionReplaySDKInstructions'

export function ProductAnalyticsFlutterInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <FlutterInstallation />
            <AdvertiseMobileReplay context="product-analytics-onboarding" sdkKey={SDKKey.FLUTTER} />
        </OnboardingDocsContentWrapper>
    )
}
